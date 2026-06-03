import os
import requests
from duckduckgo_search import DDGS
import argparse

def download_gifs_from_duckduckgo(keyword, download_dir, num_gifs=10):
    """
    Searches DuckDuckGo for GIFs based on a keyword and downloads them
    to a specified directory.

    Args:
        keyword (str): The search term for GIFs.
        download_dir (str): The directory where GIFs will be saved.
        num_gifs (int): The maximum number of GIFs to download.
    """
    print(f"Searching for '{keyword}' GIFs on DuckDuckGo...")
    results = DDGS().images(
        keywords=keyword + " gif",
        safesearch='off',  # Set to 'on' if you want to filter explicit content
        type_image='gif',
        max_results=num_gifs
    )

    if not results:
        print(f"No GIFs found for '{keyword}'.")
        return

    # Create the download directory if it doesn't exist
    os.makedirs(download_dir, exist_ok=True)
    print(f"Downloading GIFs to: {os.path.abspath(download_dir)}")

    downloaded_count = 0
    for i, result in enumerate(results):
        if downloaded_count >= num_gifs:
            break

        image_url = result.get('image')
        if not image_url:
            continue

        # Extract filename from URL or create a generic one
        filename = os.path.basename(image_url).split('?')[0]
        if not filename or '.' not in filename:
            filename = f"{keyword.replace(' ', '_')}_{i+1}.gif"
        
        file_path = os.path.join(download_dir, filename)

        try:
            print(f"Downloading {i+1}/{len(results)}: {image_url}")
            response = requests.get(image_url, stream=True, timeout=10)
            response.raise_for_status()  # Raise an exception for bad status codes

            with open(file_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            print(f"Saved: {file_path}")
            downloaded_count += 1
        except requests.exceptions.RequestException as e:
            print(f"Error downloading {image_url}: {e}")
        except Exception as e:
            print(f"An unexpected error occurred for {image_url}: {e}")

    print(f"\nFinished downloading. Total GIFs downloaded: {downloaded_count}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download GIFs from DuckDuckGo.")
    parser.add_argument("keyword", type=str, help="The keyword to search for GIFs.")
    parser.add_argument("-d", "--dir", type=str, default="downloaded_gifs",
                        help="The directory to save the GIFs. Defaults to 'downloaded_gifs'.")
    parser.add_argument("-n", "--num", type=int, default=10,
                        help="The maximum number of GIFs to download. Defaults to 10.")

    args = parser.parse_args()

    download_gifs_from_duckduckgo(args.keyword, args.dir, args.num)
