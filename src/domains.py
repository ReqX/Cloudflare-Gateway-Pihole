import os
import http.client
from urllib.parse import urlparse, urljoin
from configparser import ConfigParser
from src import info, convert, silent_error, error
from src.requests import retry, retry_config, RateLimitException, HTTPException, stop_after_custom_attempts, wait_random_exponential

# Aggressive retry config for adlist downloads (15 retries, ~5 min max wait)
adlist_retry_config = {
    'stop': lambda exc, n: stop_after_custom_attempts(n, max_attempts=15),
    'wait': lambda n: wait_random_exponential(n, multiplier=1, max_wait=30),
    'retry': lambda e: isinstance(e, HTTPException),
    'before_sleep': lambda r: info(f"Sleeping before next retry ({r['attempt_number']})")
}

# Define the DomainConverter class for processing URL lists
class DomainConverter:
    def __init__(self):
        # Map of environment variables to file paths
        self.env_file_map = {
            "ADLIST_URLS": "./lists/adlist.ini",
            "WHITELIST_URLS": "./lists/whitelist.ini",
            "DYNAMIC_BLACKLIST": "./lists/dynamic_blacklist.txt",
            "DYNAMIC_WHITELIST": "./lists/dynamic_whitelist.txt",
            "ADLIST_CACHE": "./lists/adlist_cache.txt",
            "WHITELIST_CACHE": "./lists/whitelist_cache.txt"
        }
        # Read adlist and whitelist URLs from environment and files
        self.adlist_urls = self.read_urls("ADLIST_URLS")
        self.whitelist_urls = self.read_urls("WHITELIST_URLS")

    def read_urls_from_file(self, filename):
        urls = []
        try:
            # Try reading as an INI file
            config = ConfigParser()
            config.read(filename)
            for section in config.sections():
                for key in config.options(section):
                    if not key.startswith("#"):
                        urls.append(config.get(section, key))
        except Exception:
            # Fallback to read as a plain text file
            with open(filename, "r") as file:
                urls = [
                    url.strip() for url in file if not url.startswith("#") and url.strip()
                ]
        return urls
    
    def read_urls_from_env(self, env_var):
        urls = os.getenv(env_var, "")
        return [url.strip() for url in urls.split() if url.strip()]

    def read_urls(self, env_var):
        file_path = self.env_file_map[env_var]
        urls = self.read_urls_from_file(file_path)
        urls += self.read_urls_from_env(env_var)
        return urls

    @retry(**adlist_retry_config)
    def download_file(self, url):
        parsed_url = urlparse(url)
        if parsed_url.scheme == "https":
            conn = http.client.HTTPSConnection(parsed_url.netloc, timeout=60)
        else:
            conn = http.client.HTTPConnection(parsed_url.netloc, timeout=60)

        headers = {
            'User-Agent': 'Mozilla/5.0'
        }

        try:
            conn.request("GET", parsed_url.path, headers=headers)
            response = conn.getresponse()
        except (http.client.HTTPException, ConnectionError, OSError) as e:
            conn.close()
            error_message = f"Network error downloading {url}: {e}"
            silent_error(error_message)
            raise HTTPException(error_message)

        # Handle redirection responses
        redirect_count = 0
        max_redirects = 10
        while response.status in (301, 302, 303, 307, 308):
            conn.close()  # Close old connection before redirect
            location = response.getheader('Location')
            if not location:
                break
            redirect_count += 1
            if redirect_count > max_redirects:
                conn.close()
                error_message = f"Too many redirects ({max_redirects}) for {url}"
                silent_error(error_message)
                raise HTTPException(error_message)
            # Construct new absolute URL if relative path is returned
            if not urlparse(location).netloc:
                location = urljoin(url, location)

            url = location
            parsed_url = urlparse(url)

            # Create new connection based on the new URL scheme
            if parsed_url.scheme == "https":
                conn = http.client.HTTPSConnection(parsed_url.netloc, timeout=60)
            else:
                conn = http.client.HTTPConnection(parsed_url.netloc, timeout=60)

            # Use full path with query string for redirects
            full_path = parsed_url.path
            if parsed_url.params:
                full_path += f";{parsed_url.params}"
            if parsed_url.query:
                full_path += f"?{parsed_url.query}"
            if parsed_url.fragment:
                full_path += f"#{parsed_url.fragment}"

            try:
                conn.request("GET", full_path, headers=headers)
                response = conn.getresponse()
            except (http.client.HTTPException, ConnectionError, OSError) as e:
                conn.close()
                error_message = f"Network error during redirect for {url}: {e}"
                silent_error(error_message)
                raise HTTPException(error_message)

        # Raise error for non-200 status codes
        if response.status != 200:
            error_message = f"Failed to download file from {url}, status code: {response.status}"
            silent_error(error_message)
            conn.close()
            if response.status >= 500:
                raise HTTPException(error_message)  # Use HTTPException for 5xx, gets ServerSideException treatment
            elif response.status == 429:
                raise RateLimitException(error_message)
            else:
                raise HTTPException(error_message)

        # Read response data and close the connection
        try:
            data = response.read().decode('utf-8')
        except (http.client.HTTPException, ConnectionError, OSError) as e:
            conn.close()
            error_message = f"Network error reading response from {url}: {e}"
            silent_error(error_message)
            raise HTTPException(error_message)
        conn.close()
        info(f"Downloaded file from {url}. File size: {len(data)}")
        return data

    def download_with_cache(self, url, cache_file):
        """Download with cache fallback. Returns fresh data, or cached if download fails."""
        try:
            data = self.download_file(url)
            # Update cache on successful download
            try:
                with open(cache_file, 'w') as f:
                    f.write(data)
                info(f"Updated cache: {cache_file}")
            except OSError as e:
                silent_error(f"Failed to write cache {cache_file}: {e}")
            return data
        except HTTPException as e:
            # Download failed, try cache
            try:
                with open(cache_file, 'r') as f:
                    cached_data = f.read()
                silent_error(f"Using cached data from {cache_file} (download failed: {e})")
                return cached_data
            except FileNotFoundError:
                error(f"No cache available and download failed for {url}")
                raise

    def process_urls(self):
        block_content = ""
        white_content = ""
        # Download adlists with cache fallback
        for i, url in enumerate(self.adlist_urls):
            cache_file = self.env_file_map["ADLIST_CACHE"] if i == 0 else f"{self.env_file_map['ADLIST_CACHE']}.{i}"
            block_content += self.download_with_cache(url, cache_file)
        # Download whitelists with cache fallback
        for i, url in enumerate(self.whitelist_urls):
            cache_file = self.env_file_map["WHITELIST_CACHE"] if i == 0 else f"{self.env_file_map['WHITELIST_CACHE']}.{i}"
            white_content += self.download_with_cache(url, cache_file)
        
        # Read additional dynamic lists
        dynamic_blacklist = os.getenv("DYNAMIC_BLACKLIST", "")
        dynamic_whitelist = os.getenv("DYNAMIC_WHITELIST", "")
        
        if dynamic_blacklist:
            block_content += dynamic_blacklist
        else:
            with open(self.env_file_map["DYNAMIC_BLACKLIST"], "r") as black_file:
                block_content += black_file.read()
        
        if dynamic_whitelist:
            white_content += dynamic_whitelist
        else:
            with open(self.env_file_map["DYNAMIC_WHITELIST"], "r") as white_file:
                white_content += white_file.read()
        
        # Convert the collected content into a domain list
        domains = convert.convert_to_domain_list(block_content, white_content)
        return domains
