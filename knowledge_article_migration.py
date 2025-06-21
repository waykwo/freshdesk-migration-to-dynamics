# Imports and logging

import os
import re
import logging
import requests
from requests.auth import HTTPBasicAuth
import json
import base64
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
import variables
from bs4 import BeautifulSoup
import json
from datetime import datetime, timezone
from icecream import ic
import time

# Create and configure logger
LOG_FORMAT = "%(levelname)s %(asctime)s - %(message)s"
logging.basicConfig(filename="./knowledge_article_migration.log",
                    level=logging.DEBUG,
                    format=LOG_FORMAT)
logger = logging.getLogger()

# Get datetime in UTC as string


def get_utc_datetime():
    utc_datetime = datetime.now(timezone.utc)
    return utc_datetime.strftime("%Y%m%d%H%M%S")


# Start timer
overall_start_time = datetime.now()

# Get Freshdesk API
with open("./parameters.json") as file:
    parameters = json.load(file)

freshdesk_api_key = parameters["freshdesk_api"]
freshdesk_url = "https://yourcompany.freshdesk.com/api/v2/"


# Dataverse API
global dynamics_url

# Prompt user for environment selection
environment_prompt = input(
    'Please enter "d" for Dev, "e" for DevPortal, "s" for Staging, or "p" for Production environment: ')
if environment_prompt.lower() == "d":
    # Dev
    dynamics_url = "https://yourorg-dev.crm3.dynamics.com/"
    static_refresh_token = variables.refresh_token_dev
    scope = variables.scope_dev
if environment_prompt.lower() == "e":
    # Dev Portal
    dynamics_url = "https://yourorg-devportal.crm3.dynamics.com/"
    static_refresh_token = variables.refresh_token_devportal
    scope = variables.scope_dev
elif environment_prompt.lower() == "s":
    # Staging
    dynamics_url = "https://yourorg-staging.crm3.dynamics.com/"
    static_refresh_token = variables.refresh_token_staging
    scope = variables.scope_staging
elif environment_prompt.lower() == "p":
    # Production
    dynamics_url = "https://yourorg-prod.crm3.dynamics.com/"
    static_refresh_token = variables.refresh_token_prod
    scope = variables.scope_prod

# Get secret from keyvault
key_vault_name = variables.KEY_VAULT_NAME
secret_name = "your-secret-name"
kv_uri = variables.KEY_VAULT_URI

credential = DefaultAzureCredential()
client = SecretClient(vault_url=kv_uri, credential=credential)

secret = client.get_secret(secret_name)

client_id = variables.client_id
authority = variables.authority

env = re.search(r"-(.*?).crm3", dynamics_url).group(1)


# Get access token using refresh token
def new_access_token():
    global access_token, refresh_token

    tenant = variables.tenant_id
    client_secret = secret.value

    # Check if refresh token is defined
    current_refresh_token = refresh_token if ("refresh_token" in locals(
    ) or "refresh_token" in globals()) else static_refresh_token

    redirect_uri = "https://login.microsoftonline.com/common/oauth2/nativeclient"

    token_url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": current_refresh_token,
        "grant_type": "refresh_token",
        "redirect_uri": redirect_uri,
        "scope": scope
    }

    response = requests.post(token_url, data=payload)
    if response.status_code == 200:
        token_response = response.json()
        access_token = token_response["access_token"]
        refresh_token = token_response["refresh_token"]
        logger.info("Access token refreshed!")
        print("Access token refreshed!")

        return access_token
    else:
        logger.error(f"Failed to obtain tokens: {response.status_code}")
        logger.error(response.json())
        print(f"Failed to obtain tokens: {response.status_code}")
        print(response.json())


# Create and manage API session
def create_api_session():
    """Create and configure a requests session for Dataverse API calls"""
    global access_token

    session = requests.Session()
    session.headers.update({
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
        "OData-MaxVersion": "4.0",
        "OData-Version": "4.0",
        "Accept": "application/json"
    })

    return session


# Make an API call with automatic token refresh on 401 errors
def make_api_call(session, url, method='GET', json_data=None, max_retries=3):
    """Make an API call with automatic token refresh on 401 errors"""
    global access_token

    for attempt in range(max_retries):
        try:
            if method.upper() == "GET":
                response = session.get(url)
            elif method.upper() == "POST":
                response = session.post(url, json=json_data)
            elif method.upper() == "PATCH":
                response = session.patch(url, json=json_data)
            elif method.upper() == "PUT":
                response = session.put(url, json=json_data)

            response.raise_for_status()
            return response

        except requests.exceptions.HTTPError as err:
            status_code = err.response.status_code
            if status_code == 401 and attempt < max_retries - 1:
                logger.warning(
                    "Received 401 error. Refreshing token and creating new session...")
                print("Received 401 error. Refreshing token and creating new session...")

                # Refresh token
                new_access_token()

                # Create a completely new session with the new token
                session = create_api_session()

                # Wait before retry (use exponential backoff)
                wait_time = 5 * (2 ** attempt)
                print(f"Waiting {wait_time} seconds before retrying...")
                time.sleep(wait_time)
            else:
                # If it's not a 401 or we've exceeded retries, log and raise
                logger.error(
                    f"HTTP error {status_code}: {err.response.content}")
                print(f"HTTP error {status_code}: {err.response.content}")
                raise

        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            print(f"Unexpected error: {str(e)}")
            if attempt < max_retries - 1:
                wait_time = 5 * (2 ** attempt)
                print(f"Waiting {wait_time} seconds before retrying...")
                time.sleep(wait_time)
            else:
                raise


# Freshdesk GET function
def freshdesk_get(url):
    global freshdesk_get_response
    headers = {
        "content-type": "application/json"
    }

    freshdesk_get_response = requests.get(
        url=url,
        auth=HTTPBasicAuth(freshdesk_api_key, ""),
        headers=headers
    )

    repo = freshdesk_get_response.json()

    if freshdesk_get_response.status_code == 200:
        while "next" in freshdesk_get_response.links.keys():
            freshdesk_get_response = requests.get(
                freshdesk_get_response.links["next"]["url"],
                auth=HTTPBasicAuth(freshdesk_api_key, ""),
                headers=headers
            )
            repo.extend(freshdesk_get_response.json())
            ic(f"{freshdesk_get_response.links}")
        return repo
    else:
        logger.error(freshdesk_get_response.status_code)
        ic(freshdesk_get_response.status_code)


# Function to get folders of articles from Freshdesk
def get_freshdesk_folders(category):
    global kb_folders
    kb_folders = []
    id = category["id"]
    folders_url = f"{freshdesk_url}solutions/categories/{id}/folders"
    folders = freshdesk_get(folders_url)

    for folder in folders:
        folder_data = {}
        folder_data["id"] = folder["id"]
        folder_data["name"] = folder["name"]
        folder_data["description"] = folder["description"]
        folder_data["articles_count"] = folder["articles_count"]
        folder_data["sub_folders_count"] = folder["sub_folders_count"]
        folder_data["parent_folder_id"] = folder["hierarchy"][0]["data"]["id"]
        folder_data["is_parent_folder"] = True
        folder_data["visibility"] = folder["visibility"]

        print(folder_data)

        kb_folders.append(folder_data)

        if folder_data["sub_folders_count"] > 0:
            folder_to_query = folder_data["id"]
            subfolder_url = f"{freshdesk_url}solutions/folders/{folder_to_query}/subfolders"
            subfolders = freshdesk_get(subfolder_url)
            for subfolder in subfolders:
                subfolder_data = {}
                subfolder_data["id"] = subfolder["id"]
                subfolder_data["name"] = subfolder["name"]
                subfolder_data["description"] = subfolder["description"]
                subfolder_data["articles_count"] = subfolder["articles_count"]
                subfolder_data["sub_folders_count"] = subfolder["sub_folders_count"]
                subfolder_data["parent_folder_id"] = subfolder["parent_folder_id"]
                subfolder_data["is_parent_folder"] = False
                subfolder_data["visibility"] = subfolder["visibility"]
                print(subfolder_data)

                kb_folders.append(subfolder_data)


# Initialize global dictionaries
if "internal_articles_refs_dict" not in globals():
    internal_articles_refs_dict = {}
if "migrated_articles" not in globals():
    migrated_articles = {}


# Save internal article references to JSON
def save_internal_references_to_json(output_file_path="./data/internal_article_references.json"):
    global internal_articles_refs_dict
    """
    Save the internal article references dictionary to a JSON file
    
    Args:
        output_file_path (str): Path to the output JSON file
    """

    # Ensure the directory exists
    output_dir = os.path.dirname(output_file_path)
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # Add timestamp to filename to avoid overwriting
    filename, extension = os.path.splitext(output_file_path)
    timestamp = get_utc_datetime()
    output_file_with_timestamp = f"{filename}_{timestamp}{extension}"

    # Save the internal article references to a JSON file
    with open(output_file_with_timestamp, 'w') as f:
        json.dump(internal_articles_refs_dict, f, indent=4)

    logger.info(
        f"Saved internal article references to {output_file_with_timestamp}")
    print(f"Saved internal article references to {output_file_with_timestamp}")


# Get images function (includes internal article references, even though the function is named get_images)
def get_images_and_internal_references(article, api_session=None):
    global dynamics_url, headers, images, img_dict, article_index, internal_articles_refs_dict

    # If no session is provided, create one
    if api_session is None:
        if not "access_token" in globals() or not access_token:
            new_access_token()
        api_session = create_api_session()

    # Get the current UTC datetime as string
    utc_datetime_str = get_utc_datetime()

    # Extract article ID and title
    id = article["id"]
    title = article["title"]

    if "img_dict" not in globals():
        img_dict = {}

    html_content = article["description"]
    soup = BeautifulSoup(html_content, "html.parser")

    # Extract internal article references (URLs containing your helpdesk domain)
    all_a_tags = soup.find_all("a")
    internal_articles_refs = []

    for a_tag in all_a_tags:
        if a_tag.has_attr("href"):
            href = a_tag["href"]
            # Replace with your actual helpdesk domain
            if "helpdesk.yourcompany.com" in href:
                internal_articles_refs.append(href)

    # Store the internal article references
    internal_articles_refs_dict[id] = internal_articles_refs

    # Extract img src
    img_tags = soup.find_all("img")
    img_urls = [img["src"] for img in img_tags]

    article_index = 0

    for img in img_urls:
        image_name = f"{id}_{utc_datetime_str}_{article_index}"
        local_path = f"./data/images/{image_name}.png"
        article_index += 1

        retries = 0
        success = False
        while not success and retries < 3:
            try:
                # Send a GET request to the URL
                response = requests.get(img)

                # Check if the request was successful
                if response.status_code == 200:
                    # Open a file in binary write mode
                    with open(local_path, "wb") as file:
                        # Write the content of the response (the image) to the file
                        file.write(response.content)
                    logger.info("Image successfully downloaded and saved!")
                    print("Image successfully downloaded and saved!")
                else:
                    logger.warning(f"Failed to retrieve image {image_name}.")
                    print(f"Failed to retrieve the image {image_name}.")
                    raise Exception(
                        f"Failed to download image: status code {response.status_code}")

                # Read the image file and encode it in base64
                with open(local_path, "rb") as file:
                    file_content = file.read()
                    file_base64 = base64.b64encode(
                        file_content).decode("utf-8")

                retries = 0
                success = False
                while not success and retries < 3:
                    try:
                        # Create a web resource with the image
                        web_resource_data = {
                            "name": image_name,
                            "displayname": image_name,
                            "description": f"Image for {title}",
                            "content": file_base64,
                            "webresourcetype": 5  # Type 5 for PNG images
                        }
                        web_resource_url = f"{dynamics_url}api/data/v9.2/webresourceset"

                        web_resource_response = make_api_call(
                            api_session, web_resource_url, "POST", web_resource_data)

                        logger.info(
                            f"Web resource response status code: {web_resource_response.status_code}")
                        print(
                            f"Web resource response status code: {web_resource_response.status_code}")

                        if web_resource_response.status_code in [201, 204]:
                            logger.info("Web resource created successfully!")
                            print("Web resource created successfully!")
                            # This URL should not contain "api/data/v9.2/"
                            public_url = f"{dynamics_url}WebResources/{image_name}"
                            logger.info(
                                f"Public URL for the image: {public_url}")
                            print(f"Public URL for the image: {public_url}")

                            img_dict = {
                                "article_id": id,
                                "aws_url": img,
                                "article_title": title,
                                "local_path": local_path,
                                "dynamics_image_url": public_url
                            }

                            images[image_name] = img_dict
                            success = True
                        else:
                            logger.warning(
                                f"Failed to create web resource for image: {image_name}.")
                            print(
                                f"Failed to create web resource. Status code: {web_resource_response.status_code}")
                            try:
                                logger.error(web_resource_response.json())
                                print(web_resource_response.json())
                            except json.JSONDecodeError:
                                logger.error("No JSON response body.")
                                print("No JSON response body.")
                            raise Exception(
                                f"Failed to create web resource: {web_resource_response.status_code}")

                    except requests.exceptions.RequestException as err:
                        logger.warning(
                            f"Failed to create web resource for image: {image_name}. Error: {err}")
                        print(
                            f"Failed to create web resource for image: {image_name}. Error: {err}")
                        retries += 1
                        if retries < 3:
                            logger.warning(
                                f"Retrying web resource creation for {image_name} after 6 minutes...")
                            print(
                                f"Retrying web resource creation for {image_name} after 6 minutes...")
                            # Wait for 6 minutes before retrying
                            time.sleep(360)

                            # Refresh token and session before retry
                            new_access_token()
                            api_session = create_api_session()
                    except Exception as err:
                        logger.warning(
                            f"Other error in web resource creation: {err}")
                        print(f"Other error in web resource creation: {err}")
                        retries += 1
                        if retries < 3:
                            logger.warning(
                                f"Retrying web resource creation for {image_name} after 6 minutes...")
                            print(
                                f"Retrying web resource creation for {image_name} after 6 minutes...")
                            # Wait for 6 minutes before retrying
                            time.sleep(360)

                            # Refresh token and session before retry
                            new_access_token()
                            api_session = create_api_session()

            except requests.exceptions.RequestException as err:
                logger.warning(
                    f"Failed to migrate image {image_name} for {title}. Error: {err}")
                print(
                    f"Failed to migrate image {image_name} for {title}. Error: {err}")
                retries += 1
                if retries < 3:
                    logger.warning(
                        f"Retrying {image_name} migration after 6 minutes...")
                    print(
                        f"Retrying {image_name} migration after 6 minutes...")
                    time.sleep(360)  # Wait for 6 minutes before retrying
            except Exception as err:
                logger.warning(f"Other error in image migration: {err}")
                print(f"Other error in image migration: {err}")
                retries += 1
                if retries < 3:
                    logger.warning(
                        f"Retrying {image_name} migration after 6 minutes...")
                    print(
                        f"Retrying {image_name} migration after 6 minutes...")
                    time.sleep(360)  # Wait for 6 minutes before retrying


# Add categories to Dynamics function
def import_categories_to_dynamics(category_set):
    global access_token, imported_categories, dynamics_url

    # Ensure we have a valid token
    if not "access_token" in globals() or not access_token:
        new_access_token()

    # Create a session
    api_session = create_api_session()

    for category in category_set:
        category_name = category["name"]
        category_description = category["description"]
        freshdesk_category_id = category["id"]

        # Top-level categories
        if "is_top_level" in category and category["is_top_level"] == 1:
            category_data = {
                "title": category_name,
                "description": category_description,
                "revops_freshdeskcategoryid": freshdesk_category_id,
                "revops_istoplevelcategory": True
            }

        else:
            # In FD, visibility == 1 is external; 2 is logged in users; 3 is internal
            # In Dynamics, isinternal == 1 means it is internal; 0 means external

            # Top-level folders
            if category["is_parent_folder"] == True:
                parent_category_id = category["parent_folder_id"]
                isinternal = False if category["visibility"] == 1 else True
                category_data = {
                    "title": category_name,
                    "description": category_description,
                    "revops_freshdeskcategoryid": freshdesk_category_id,
                    "revops_istoplevelcategory": False,
                    "revops_isinternal": isinternal,
                    "parentcategoryid@odata.bind": f'/categories({imported_categories[parent_category_id]["categoryid"]})'
                }

            # Subfolders
            elif category["is_parent_folder"] == False:
                parent_category_id = category["parent_folder_id"]
                isinternal = False if category["visibility"] == 1 else True
                category_data = {
                    "title": category_name,
                    "description": category_description,
                    "revops_freshdeskcategoryid": freshdesk_category_id,
                    "revops_istoplevelcategory": False,
                    "revops_isinternal": isinternal,
                    "parentcategoryid@odata.bind": f'/categories({imported_categories[parent_category_id]["categoryid"]})'
                }

        categories_url = f"{dynamics_url}api/data/v9.2/categories"

        try:
            categories_response = make_api_call(
                api_session, categories_url, "POST", category_data)

            if categories_response.status_code in [201, 204]:
                print("Category added successfully!")
                imported_category = {}
                freshdesk_id = category["id"]
                imported_category["categoryid"] = categories_response.json()[
                    "categoryid"]
                imported_category["title"] = categories_response.json()[
                    "title"]
                imported_categories.update({freshdesk_id: imported_category})
            else:
                logger.warning(f"Failed to create category {category_name}.")
                print(
                    f"Failed to create category. Status code: {categories_response.status_code}")

            try:
                print(categories_response.json())
            except json.JSONDecodeError:
                print("No JSON response body.")

        except Exception as e:
            logger.error(f"Error creating category {category_name}: {str(e)}")
            print(f"Error creating category {category_name}: {str(e)}")


# Update knowledgearticle_category function
def update_category(freshdesk_article_id, dynamics_article_id, dynamics_category_id, api_session, max_retries=3):
    global access_token

    # URLs to update the knowledge article categories
    related_category_url = f"{dynamics_url}api/data/v9.2/knowledgearticles({dynamics_article_id})/knowledgearticle_category/$ref"
    custom_lookup_url = f"{dynamics_url}api/data/v9.2/knowledgearticles({dynamics_article_id})"

    # Log the IDs being used
    logger.info(
        f"Updating category for article {freshdesk_article_id}, dynamics ID: {dynamics_article_id}, category ID: {dynamics_category_id}")

    success = False
    retries = 0

    while not success and retries < max_retries:
        try:
            # Update custom category lookup field
            lookup_data = {
                "revops_category@odata.bind": f"/categories({dynamics_category_id})"
            }
            update_lookup_response = make_api_call(
                api_session, custom_lookup_url, "PATCH", lookup_data)

            # Update related category
            category_data = {
                "@odata.id": f"{dynamics_url}api/data/v9.2/categories({dynamics_category_id})"
            }
            update_category_response = make_api_call(
                api_session, related_category_url, "POST", category_data)

            logger.info(
                f"Knowledge category updated successfully for {freshdesk_article_id}.")
            print(
                f"Knowledge category updated successfully for article {freshdesk_article_id}")
            success = True
            return True

        except Exception as err:
            logger.error(
                f"Knowledge category update failed for {freshdesk_article_id}: {str(err)}")
            print(
                f"Knowledge category update failed for {freshdesk_article_id}: {str(err)}")
            retries += 1

            if retries < max_retries:
                logger.warning(
                    f"Retrying category update for {freshdesk_article_id} after 30 seconds... (Attempt {retries+1}/{max_retries})")
                print(
                    f"Retrying category update for {freshdesk_article_id} after 30 seconds... (Attempt {retries+1}/{max_retries})")
                time.sleep(30)  # Shorter wait time for category updates

                # Consider refreshing token between retries if needed
                if retries == max_retries - 1:  # Last attempt, try with fresh token
                    logger.info(
                        f"Refreshing token for final category update attempt on article {freshdesk_article_id}")
                    new_access_token()
                    api_session = create_api_session()

    return False  # All retries failed


# Get article number with retry logic
def get_article_number_with_retry(api_session, dynamics_knowledgearticleid, max_retries=5):
    """
    Retrieve article number with retry logic, as it may be generated asynchronously
    """
    article_details_url = f"{dynamics_url}api/data/v9.2/knowledgearticles({dynamics_knowledgearticleid})?$select=articlepublicnumber,title"

    for attempt in range(max_retries):
        try:
            article_details_response = make_api_call(
                api_session, article_details_url, "GET")
            article_details = article_details_response.json()
            article_number = article_details.get("articlepublicnumber")

            if article_number:
                logger.info(
                    f"Retrieved article number {article_number} on attempt {attempt + 1}")
                print(
                    f"Retrieved article number {article_number} on attempt {attempt + 1}")
                return article_number
            else:
                # Article number not yet generated
                if attempt < max_retries - 1:
                    wait_time = 5 * (attempt + 1)  # 5, 10, 15, 20, 25 seconds
                    logger.info(
                        f"Article number not yet available, waiting {wait_time} seconds...")
                    print(
                        f"Article number not yet available, waiting {wait_time} seconds...")
                    time.sleep(wait_time)

        except Exception as err:
            logger.error(f"Error retrieving article number: {err}")
            print(f"Error retrieving article number: {err}")
            if attempt < max_retries - 1:
                time.sleep(5)

    logger.warning(
        f"Could not retrieve article number after {max_retries} attempts")
    return None  # Article number couldn't be retrieved


# Update article numbers for all migrated articles
def update_article_numbers(api_session=None):
    """
    Update article numbers for all migrated articles that don't have them
    """
    global migrated_articles

    if api_session is None:
        if not "access_token" in globals() or not access_token:
            new_access_token()
        api_session = create_api_session()

    updated_count = 0

    for fd_article_id, article_data in migrated_articles.items():
        # Check English article
        if not article_data.get("en_articlenumber"):
            en_id = article_data["en_knowledgearticleid"]
            article_number = get_article_number_with_retry(api_session, en_id)

            if article_number:
                article_data["en_articlenumber"] = article_number
                updated_count += 1
                logger.info(
                    f"Updated article number for English article {fd_article_id}: {article_number}")
                print(
                    f"Updated article number for English article {fd_article_id}: {article_number}")

        # Check French article if exists
        if "fr_knowledgearticleid" in article_data and not article_data.get("fr_articlenumber"):
            fr_id = article_data["fr_knowledgearticleid"]
            fr_article_number = get_article_number_with_retry(
                api_session, fr_id)

            if fr_article_number:
                article_data["fr_articlenumber"] = fr_article_number
                updated_count += 1
                logger.info(
                    f"Updated article number for French article {fd_article_id}: {fr_article_number}")
                print(
                    f"Updated article number for French article {fd_article_id}: {fr_article_number}")

    logger.info(f"Updated {updated_count} article numbers")
    print(f"Updated {updated_count} article numbers")
    return updated_count


# Function to get articles from Freshdesk and save locally
def download_freshdesk_articles(kb_folder):
    global articles
    articles = []
    article_download_datetime = get_utc_datetime()

    for folder in kb_folder:
        print(folder["name"])
        freshdesk_category_id = folder["id"]
        dynamics_category_id = imported_categories[freshdesk_category_id]["categoryid"]
        category_visibility = folder["visibility"]
        # In FD, visibility == 1 is external; 2 is logged in users; 3 is internal
        # In Dynamics, isinternal == 1 means it is internal; 0 means external
        dynamics_isinternal = False if category_visibility == 1 else True

        articles_in_folder_url = f"{freshdesk_url}solutions/folders/{freshdesk_category_id}/articles"
        articles_in_folder = freshdesk_get(articles_in_folder_url)

        for article in articles_in_folder:
            article["dynamics_category_id"] = dynamics_category_id
            article["dynamics_isinternal"] = dynamics_isinternal

            articles.append(article)

    with open(f"./data/freshdesk_articles_{article_download_datetime}.json", "w") as freshdesk_data_file:
        json.dump(articles, freshdesk_data_file, indent=4)

    print("Freshdesk data saved.")


# Functions to migrate Freshdesk articles to Dataverse
def replace_image_urls(soup):
    global images
    for key, value in images.items():
        aws_url = value["aws_url"]
        dynamics_image_url = value["dynamics_image_url"]
        for img in soup.find_all("img", src=aws_url):
            img["src"] = dynamics_image_url


def migrate_to_dynamics(articles):
    global access_token, article_count, images, migrated_articles, update_category_response

    # Ensure we have a valid token
    if not "access_token" in globals() or not access_token:
        new_access_token()

    # Create a session
    api_session = create_api_session()

    kb_url = f"{dynamics_url}api/data/v9.2/knowledgearticles"

    # Initialize migrated_articles if not already defined
    if "migrated_articles" not in globals():
        migrated_articles = {}

    migrate_articles_datetime = get_utc_datetime()

    for article in articles:
        images = {}
        get_images_and_internal_references(article, api_session)

        html_content = article["description"]
        soup = BeautifulSoup(html_content, "html.parser")
        replace_image_urls(soup)

        freshdesk_article_id = int(article["id"])
        article_title = article["title"]

        # Check the status of the Freshdesk article
        # In Freshdesk: status 1 = Draft, status 2 = Published
        freshdesk_article_status = article.get("status", 0)

        # Map Freshdesk status to Dynamics status
        # In Dynamics: statecode 0 = Draft, statecode 3 = Published
        if freshdesk_article_status == 1:
            # Draft in Freshdesk
            dynamics_statecode = 0  # Draft
            dynamics_statuscode = 2  # Draft
            logger.info(
                f"Article {freshdesk_article_id} is in draft status in Freshdesk, will keep as draft in Dynamics")
            print(
                f"Article {freshdesk_article_id} is in draft status in Freshdesk, will keep as draft in Dynamics")
        else:
            # Published in Freshdesk or any other status
            dynamics_statecode = 3  # Published
            dynamics_statuscode = 7  # Published

        # Create article without statecode/statuscode initially
        article_data = {
            "title": article_title,
            "revops_freshdeskarticleid": freshdesk_article_id,
            "content": f"{soup}",
            "isinternal": article["dynamics_isinternal"],
            "publishon": article["created_at"]
            # Removed statecode and statuscode from initial creation
        }

        logger.info(f"Migrating article {freshdesk_article_id}")
        print(f"Migrating article {freshdesk_article_id}")

        retries = 0
        success = False
        while not success and retries < 3:
            try:
                dynamics_article_response = make_api_call(
                    api_session, kb_url, "POST", article_data)
                success = True
            except requests.exceptions.HTTPError as err:
                logger.error(f"HTTP error occurred: {err}")
                print(f"HTTP error occurred: {err}")
                retries += 1
                if retries < 3:
                    logger.warning(
                        f"Retrying {freshdesk_article_id} after 6 minutes...")
                    print(
                        f"Retrying {freshdesk_article_id} after 6 minutes...")
                    time.sleep(360)  # Wait for 6 minutes before retrying

                    # Refresh token and session before retry
                    new_access_token()
                    api_session = create_api_session()
            except Exception as err:
                logger.error(f"Other error occurred: {err}")
                print(f"Other error occurred: {err}")
                retries += 1
                if retries < 3:
                    logger.warning(
                        f"Retrying {freshdesk_article_id} after 6 minutes...")
                    print(
                        f"Retrying {freshdesk_article_id} after 6 minutes...")
                    time.sleep(360)  # Wait for 6 minutes before retrying

                    # Refresh token and session before retry
                    new_access_token()
                    api_session = create_api_session()

        if success and dynamics_article_response.status_code in [201, 204]:
            logger.info(
                f"Knowledge article created successfully for {freshdesk_article_id} - Count: {article_count}.")
            print(
                f"Knowledge article created successfully for {freshdesk_article_id} - Count: {article_count}.")
            article_count += 1

            dynamics_knowledgearticleid = dynamics_article_response.json()[
                "knowledgearticleid"]

            # Add delay before retrieving article number
            time.sleep(10)  # Give time for article number to be generated

            # Get the article number using retry logic
            article_number = get_article_number_with_retry(
                api_session, dynamics_knowledgearticleid)

            if not article_number:
                logger.warning(
                    f"Could not retrieve article number for article {freshdesk_article_id}")
                print(
                    f"Could not retrieve article number for article {freshdesk_article_id}")

            # Store in migrated_articles with article number and status
            migrated_articles[freshdesk_article_id] = {
                "en_knowledgearticleid": dynamics_knowledgearticleid,
                "en_title": article_title,
                "en_articlenumber": article_number,
                "fd_status": freshdesk_article_status,
                "dynamics_statecode": dynamics_statecode,
                "dynamics_statuscode": dynamics_statuscode,
                "attachment_count": len(article["attachments"]),
                "attachments": article["attachments"],
                "internal_references": internal_articles_refs_dict.get(freshdesk_article_id, [])
            }

            # Add a small delay before updating category to ensure article is fully created
            time.sleep(5)  # 5 seconds delay

            # Update article category in Dynamics
            dynamics_category_id = article["dynamics_category_id"]

            # Call update_category with retry logic and check the result
            category_update_success = update_category(
                freshdesk_article_id, dynamics_knowledgearticleid, dynamics_category_id, api_session)

            # Add a check for category update success
            if not category_update_success:
                logger.warning(
                    f"Failed to update category for article {freshdesk_article_id} after all retries")
                print(
                    f"Failed to update category for article {freshdesk_article_id} after all retries")

            # Set the article state based on the Freshdesk status
            publish_url = f"{dynamics_url}api/data/v9.2/knowledgearticles({dynamics_knowledgearticleid})"
            publish_data = {
                "statecode": dynamics_statecode,    # 0 for Draft, 3 for Published
                "statuscode": dynamics_statuscode   # 2 for Draft, 7 for Published
            }

            retries = 0
            publish_success = False
            while not publish_success and retries < 3:
                try:
                    publish_response = make_api_call(
                        api_session, publish_url, "PATCH", publish_data)
                    publish_success = True
                    if dynamics_statecode == 3:
                        logger.info(
                            f"Article {freshdesk_article_id} successfully published")
                        print(
                            f"Article {freshdesk_article_id} successfully published")
                    else:
                        logger.info(
                            f"Article {freshdesk_article_id} set to draft status")
                        print(
                            f"Article {freshdesk_article_id} set to draft status")
                except Exception as err:
                    logger.error(
                        f"Failed to set status for article {freshdesk_article_id}: {err}")
                    print(
                        f"Failed to set status for article {freshdesk_article_id}: {err}")
                    retries += 1
                    if retries < 3:
                        logger.warning(
                            f"Retrying status update for {freshdesk_article_id} after 30 seconds...")
                        print(
                            f"Retrying status update for {freshdesk_article_id} after 30 seconds...")
                        time.sleep(30)

                        # Refresh token if needed
                        if retries == 2:  # Last retry attempt
                            new_access_token()
                            api_session = create_api_session()

            # Check for French article
            try:
                french_translation_url = f"{freshdesk_url}solutions/articles/{freshdesk_article_id}/fr"
                french_translation = freshdesk_get(french_translation_url)
                logger.info(
                    f"French article found for {freshdesk_article_id}.")
                print(f"French article found for {freshdesk_article_id}.")

                # Use French - France locale (adjust based on your needs)
                fr_fr_languagelocaleid = language_dict["French - France"]

                translation_data = {
                    "Source": {
                        "@odata.type": "Microsoft.Dynamics.CRM.knowledgearticle",
                        "knowledgearticleid": dynamics_knowledgearticleid
                    },
                    "Language": {
                        "@odata.type": "Microsoft.Dynamics.CRM.languagelocale",
                        "languagelocaleid": fr_fr_languagelocaleid
                    },
                    "IsMajor": True
                }

                # Create French translation if French article exists
                if french_translation:
                    create_translation_url = f"{dynamics_url}api/data/v9.2/CreateKnowledgeArticleTranslation"

                    retries = 0
                    success = False
                    while not success and retries < 3:
                        try:
                            translation_response = make_api_call(
                                api_session, create_translation_url, "POST", translation_data)
                            success = True
                        except requests.exceptions.HTTPError as err:
                            logger.error(f"Error: {err}")
                            print(f"Error: {err}")
                            retries += 1
                            if retries < 3:
                                logger.warning(
                                    f"Retrying {freshdesk_article_id} create FR translation after 6 minutes...")
                                print(
                                    f"Retrying {freshdesk_article_id} create FR translation after 6 minutes...")
                                # Wait for 6 minutes before retrying
                                time.sleep(360)

                                # Refresh token and session before retry
                                new_access_token()
                                api_session = create_api_session()

                    images = {}
                    get_images_and_internal_references(
                        french_translation, api_session)

                    fr_content = french_translation["description"]
                    soup = BeautifulSoup(fr_content, "html.parser")
                    replace_image_urls(soup)

                    fr_title = french_translation["title"]
                    translated_article_id = translation_response.json()[
                        "knowledgearticleid"]
                    fr_article_url = f"{dynamics_url}api/data/v9.2/knowledgearticles({translated_article_id})"

                    french_data = {
                        "content": f"{soup}",
                        "title": fr_title
                    }

                    retries = 0
                    success = False
                    while not success and retries < 3:
                        try:
                            update_fr_content_response = make_api_call(
                                api_session, fr_article_url, "PATCH", french_data)
                            success = True
                            article_count += 1
                        except Exception as err:
                            logger.error(
                                f"French article update failed for {freshdesk_article_id}: {err}")
                            print(
                                f"French article update failed for {freshdesk_article_id}: {err}")
                            retries += 1
                            if retries < 3:
                                logger.warning(
                                    f"Retrying {freshdesk_article_id} FR after 6 minutes...")
                                print(
                                    f"Retrying {freshdesk_article_id} FR after 6 minutes...")
                                # Wait for 6 minutes before retrying
                                time.sleep(360)

                                # Refresh token and session before retry
                                new_access_token()
                                api_session = create_api_session()

                    # Add delay before retrieving French article number
                    time.sleep(10)

                    # Get the French article number using retry logic
                    fr_article_number = get_article_number_with_retry(
                        api_session, translated_article_id)

                    if not fr_article_number:
                        logger.warning(
                            f"Could not retrieve French article number for article {freshdesk_article_id}")
                        print(
                            f"Could not retrieve French article number for article {freshdesk_article_id}")

                    # Add French article info to migrated_articles
                    migrated_articles[freshdesk_article_id].update({
                        "fr_knowledgearticleid": translated_article_id,
                        "fr_title": fr_title,
                        "fr_articlenumber": fr_article_number
                    })
                    logger.info(
                        f"Knowledge article French content updated successfully for {freshdesk_article_id} - Count: {article_count}.")
                    print(
                        f"Knowledge article French content updated successfully for {freshdesk_article_id} - Count: {article_count}.")

                    # Add delay before updating category for French article
                    time.sleep(5)  # 5 seconds delay

                    # Update category for French article
                    fr_category_update_success = update_category(
                        freshdesk_article_id, translated_article_id, dynamics_category_id, api_session)
                    if not fr_category_update_success:
                        logger.warning(
                            f"Failed to update category for French article {freshdesk_article_id} after all retries")
                        print(
                            f"Failed to update category for French article {freshdesk_article_id} after all retries")

                    # Set the French article state based on the Freshdesk status
                    fr_publish_url = f"{dynamics_url}api/data/v9.2/knowledgearticles({translated_article_id})"
                    fr_publish_data = {
                        "statecode": dynamics_statecode,    # 0 for Draft, 3 for Published
                        "statuscode": dynamics_statuscode   # 2 for Draft, 7 for Published
                    }

                    retries = 0
                    fr_publish_success = False
                    while not fr_publish_success and retries < 3:
                        try:
                            fr_publish_response = make_api_call(
                                api_session, fr_publish_url, "PATCH", fr_publish_data)
                            fr_publish_success = True
                            if dynamics_statecode == 3:
                                logger.info(
                                    f"French translation for article {freshdesk_article_id} successfully published")
                                print(
                                    f"French translation for article {freshdesk_article_id} successfully published")
                            else:
                                logger.info(
                                    f"French translation for article {freshdesk_article_id} set to draft status")
                                print(
                                    f"French translation for article {freshdesk_article_id} set to draft status")
                        except Exception as err:
                            logger.error(
                                f"Failed to set status for French article {freshdesk_article_id}: {err}")
                            print(
                                f"Failed to set status for French article {freshdesk_article_id}: {err}")
                            retries += 1
                            if retries < 3:
                                logger.warning(
                                    f"Retrying status update for French article {freshdesk_article_id} after 30 seconds...")
                                print(
                                    f"Retrying status update for French article {freshdesk_article_id} after 30 seconds...")
                                time.sleep(30)

                                # Refresh token if needed
                                if retries == 2:  # Last retry attempt
                                    new_access_token()
                                    api_session = create_api_session()

            except Exception as err:
                logger.warning(
                    f"No French article found for {freshdesk_article_id}: {err}")
                print(
                    f"No French article found for {freshdesk_article_id}: {err}")

        else:
            logging.error(
                f"An error occurred: {dynamics_article_response.content if 'dynamics_article_response' in locals() else 'No response'}")
            print(
                f"Failed to create knowledge article: {dynamics_article_response.content if 'dynamics_article_response' in locals() else 'No response'}")
            try:
                if 'dynamics_article_response' in locals():
                    print(dynamics_article_response.json())
            except json.JSONDecodeError:
                print("No JSON response body.")

    migrate_articles_datetime = get_utc_datetime()

    with open(f"./data/migrated_articles_{env}_{migrate_articles_datetime}.json", "w") as migrated_data_file:
        json.dump(migrated_articles, migrated_data_file, indent=4)

    print("Migrated article data saved.")


def update_internal_links(api_session=None):
    """Update internal links in migrated articles using the current mappings"""
    global migrated_articles, internal_articles_refs_dict

    # Ensure we have a valid session
    if api_session is None:
        if "access_token" not in globals() or not access_token:
            new_access_token()
        api_session = create_api_session()

    # Create a mapping of Freshdesk URLs to Dynamics URLs
    url_mapping = {}

    logger.info("Building URL mapping for internal article references")
    print("Building URL mapping for internal article references")

    # Extract the base portal URL from the Dynamics URL
    # Usually portal URL is something like: https://[org]-[env].powerappsportals.com/
    portal_base_url = dynamics_url.replace(
        "crm3.dynamics.com/", "powerappsportals.com/")

    # For each migrated article, find its internal references
    for fd_article_id, article_data in migrated_articles.items():
        # Skip if this article doesn't have internal references
        if str(fd_article_id) not in internal_articles_refs_dict:
            continue

        # For each reference URL in this article
        for url in internal_articles_refs_dict[str(fd_article_id)]:
            # Try to extract the Freshdesk article ID from the URL
            fd_id_match = re.search(r'articles/(\d+)', url)
            if fd_id_match:
                ref_fd_id = int(fd_id_match.group(1))
                # If this referenced article has been migrated
                if ref_fd_id in migrated_articles:
                    # Use the article number for the portal URL
                    ref_article_number = migrated_articles[ref_fd_id].get(
                        'en_articlenumber')
                    # Check if the referenced article is published
                    ref_is_published = migrated_articles[ref_fd_id].get(
                        'dynamics_statecode') == 3

                    if ref_article_number:
                        # Create the portal URL for the article
                        ref_dynamics_url = f"{portal_base_url}knowledgebase/article/{ref_article_number}/"

                        # Add to mapping with a note if it's a draft
                        url_mapping[url] = {
                            'url': ref_dynamics_url,
                            'is_published': ref_is_published
                        }

                        status_note = "published" if ref_is_published else "draft"
                        logger.info(
                            f"Mapped Freshdesk URL {url} to Dynamics URL {ref_dynamics_url} (status: {status_note})")

    # Now update all migrated articles with the new URLs
    logger.info(f"Found {len(url_mapping)} internal URLs to update")
    print(f"Found {len(url_mapping)} internal URLs to update")

    updated_count = 0

    # For each migrated article
    for fd_article_id, article_data in migrated_articles.items():
        # English article
        en_article_id = article_data['en_knowledgearticleid']
        article_url = f"{dynamics_url}api/data/v9.2/knowledgearticles({en_article_id})"

        try:
            # Get current content
            article_response = make_api_call(api_session, article_url, "GET")
            article_content = article_response.json().get("content", "")

            # Parse content with BeautifulSoup
            soup = BeautifulSoup(article_content, "html.parser")

            # Track if we made any changes to this article
            article_updated = False

            # For each link in the mapping
            for old_url, new_url_data in url_mapping.items():
                new_url = new_url_data['url']
                is_published = new_url_data['is_published']

                # Find all links with this URL
                for a_tag in soup.find_all("a", href=old_url):
                    a_tag['href'] = new_url

                    # Add a note in the link title if it's a draft
                    if not is_published:
                        # Preserve existing title if any
                        existing_title = a_tag.get('title', '')
                        if existing_title:
                            a_tag['title'] = f"{existing_title} (Note: This article is currently in draft status)"
                        else:
                            a_tag['title'] = "Note: This article is currently in draft status"

                    article_updated = True
                    status_note = "published" if is_published else "draft"
                    logger.info(
                        f"Updated link in article {fd_article_id} from {old_url} to {new_url} (status: {status_note})")

            # If we updated any links, save the content
            if article_updated:
                update_data = {
                    "content": str(soup)
                }

                update_response = make_api_call(
                    api_session, article_url, "PATCH", update_data)

                if update_response.status_code in [204, 200]:
                    updated_count += 1
                    logger.info(
                        f"Successfully updated links in article {fd_article_id}")
                    print(
                        f"Successfully updated links in article {fd_article_id}")
                else:
                    logger.warning(
                        f"Failed to update links in article {fd_article_id}")
                    print(f"Failed to update links in article {fd_article_id}")

            # Check for French translation
            if "fr_knowledgearticleid" in article_data:
                fr_article_id = article_data["fr_knowledgearticleid"]
                fr_article_url = f"{dynamics_url}api/data/v9.2/knowledgearticles({fr_article_id})"

                # Get French content
                fr_article_response = make_api_call(
                    api_session, fr_article_url, "GET")
                fr_article_content = fr_article_response.json().get("content", "")

                # Parse French content
                fr_soup = BeautifulSoup(fr_article_content, "html.parser")

                # Track if we made any changes
                fr_article_updated = False

                # Update French links
                for old_url, new_url_data in url_mapping.items():
                    new_url = new_url_data['url']
                    is_published = new_url_data['is_published']

                    for a_tag in fr_soup.find_all("a", href=old_url):
                        a_tag['href'] = new_url

                        # Add a note in the link title if it's a draft (in French)
                        if not is_published:
                            # Preserve existing title if any
                            existing_title = a_tag.get('title', '')
                            if existing_title:
                                a_tag['title'] = f"{existing_title} (Remarque: Cet article est actuellement à l'état de brouillon)"
                            else:
                                a_tag['title'] = "Remarque: Cet article est actuellement à l'état de brouillon"

                        fr_article_updated = True
                        status_note = "published" if is_published else "draft"
                        logger.info(
                            f"Updated link in French article {fd_article_id} from {old_url} to {new_url} (status: {status_note})")

                # If we updated any links, save the content
                if fr_article_updated:
                    fr_update_data = {
                        "content": str(fr_soup)
                    }

                    fr_update_response = make_api_call(
                        api_session, fr_article_url, "PATCH", fr_update_data)

                    if fr_update_response.status_code in [204, 200]:
                        updated_count += 1
                        logger.info(
                            f"Successfully updated links in French article {fd_article_id}")
                        print(
                            f"Successfully updated links in French article {fd_article_id}")
                    else:
                        logger.warning(
                            f"Failed to update links in French article {fd_article_id}")
                        print(
                            f"Failed to update links in French article {fd_article_id}")

        except Exception as err:
            logger.error(
                f"Error updating links in article {fd_article_id}: {str(err)}")
            print(
                f"Error updating links in article {fd_article_id}: {str(err)}")

    logger.info(f"Updated internal links in {updated_count} articles")
    print(f"Updated internal links in {updated_count} articles")

    return updated_count


# Function to process articles in chunks
def process_articles_in_chunks(articles, chunk_size=50):
    """
    Process articles in chunks with automatic session management.

    Args:
        articles: List of articles to process
        chunk_size: Number of articles to process in each chunk
    """
    global access_token, chunk, migrated_articles
    chunk_number = 1

    # Initialize migrated_articles if not already defined
    if "migrated_articles" not in globals():
        migrated_articles = {}

    # Ensure we have a valid token
    new_access_token()

    # Process all articles in chunks
    for i in range(0, len(articles), chunk_size):
        # Log chunk information
        logger.info(f"=== Processing Chunk {chunk_number} ===")
        print(f"=== Processing Chunk {chunk_number} ===")

        # Get the current chunk of articles
        chunk = articles[i:i + chunk_size]

        # Process the current chunk
        migrate_to_dynamics(chunk)

        # Create session for post-processing
        api_session = create_api_session()

        # Update article numbers for articles that don't have them
        logger.info("Checking for missing article numbers...")
        print("Checking for missing article numbers...")
        update_article_numbers(api_session)

        # Update internal links after each chunk
        update_internal_links(api_session)

        # Save the current state of migrated_articles after each chunk
        migrate_articles_datetime = get_utc_datetime()
        with open(f"./data/migrated_articles_{env}_{migrate_articles_datetime}.json", "w") as migrated_data_file:
            json.dump(migrated_articles, migrated_data_file, indent=4)

        # Increment the chunk counter
        chunk_number += 1

        # Calculate and log total elapsed time
        total_elapsed_time = datetime.now() - overall_start_time
        total_elapsed_minutes = total_elapsed_time.total_seconds() / 60
        logger.info(
            f"Total processing time: {total_elapsed_minutes:.2f} minutes")
        print(f"Total processing time: {total_elapsed_minutes:.2f} minutes")

        # Refresh token between chunks to ensure we have a fresh session
        new_access_token()


# Get Freshdesk categories as categories
categories_url = f"{freshdesk_url}solutions/categories/"
categories = freshdesk_get(categories_url)

top_level_categories = []

for category in categories:
    top_level_categories.append(category["id"])
    category["is_top_level"] = 1


new_access_token()


# Get categories from Dynamics
global access_token, dynamics_categories_dict

# Ensure we have a valid token
if not "access_token" in globals() or not access_token:
    new_access_token()

# Create a session
api_session = create_api_session()

dynamics_categories_url = f"{dynamics_url}api/data/v9.2/categories"

try:
    dynamics_categories_response = make_api_call(
        api_session, dynamics_categories_url, "GET")

    dynamics_categories = [item for item in dynamics_categories_response.json()[
        "value"]]

    dynamics_categories_dict = {}

    for item in dynamics_categories:
        dynamics_categories_dict.update({item["revops_freshdeskcategoryid"]: {
            "title": item["title"],
            "categoryid": item["categoryid"],
            "parent_category_id": item["_parentcategoryid_value"],
            "category_number": item["categorynumber"]
        }})

except Exception as e:
    logger.error(f"Failed to get categories: {str(e)}")
    print(f"Failed to get categories: {str(e)}")


# Save categories
env = re.search(r"-(.*?).crm3", dynamics_url).group(1)

dyn_category_query_datetime = get_utc_datetime()
with open(f"./data/imported_categories_{dyn_category_query_datetime}_{env}_env.json", "w") as json_file:
    json.dump(dynamics_categories_dict, json_file)


# Add categories to dynamics
global imported_categories
imported_categories = {}

import_categories_prompt = input("Import Freshdesk categories? (y/n): ")
if import_categories_prompt.lower() == "y":
    import_categories_to_dynamics(categories)
    for category in categories:
        get_freshdesk_folders(category)
        import_categories_to_dynamics(kb_folders)
else:
    print("No categories were added.")
    imported_categories = dynamics_categories_dict


# Get languages

# Ensure we have a valid token
if not "access_token" in globals() or not access_token:
    new_access_token()

# Create a session
api_session = create_api_session()

languages_url = f"{dynamics_url}api/data/v9.2/languagelocale"

try:
    response = make_api_call(api_session, languages_url, "GET")

    languages = response.json().get("value", [])
    language_dict = {}
    for language in languages:
        language_dict[language["name"]] = language["languagelocaleid"]

except Exception as e:
    logger.error(f"Failed to retrieve languages: {str(e)}")
    print(f"Failed to retrieve languages: {str(e)}")


# Run full import to Dynamics
article_count = 1

# Start with a fresh token
new_access_token()

for category in categories:
    # Create a session for this category's processing
    api_session = create_api_session()

    # Get all folders for this category
    get_freshdesk_folders(category)
    print(f"Found {len(kb_folders)} folders in category")

    # Download articles from Freshdesk
    download_freshdesk_articles(kb_folders)
    print(f"Downloaded {len(articles)} articles")

    # Process all articles in chunks with automatic token refresh
    process_articles_in_chunks(articles)

    # Save internal article references
    save_internal_references_to_json()

    # Refresh token after completing a full category
    new_access_token()


# FINAL ARTICLE NUMBER UPDATE - Run this if you still have articles without article numbers
# def final_article_number_update():
#     """
#     Final pass to update any remaining articles without article numbers
#     """
#     global migrated_articles

#     # Create a fresh session
#     new_access_token()
#     api_session = create_api_session()

#     logger.info("=== Running final article number update ===")
#     print("=== Running final article number update ===")

#     # Count articles missing article numbers
#     missing_en = sum(1 for article in migrated_articles.values() if not article.get("en_articlenumber"))
#     missing_fr = sum(1 for article in migrated_articles.values()
#                      if "fr_knowledgearticleid" in article and not article.get("fr_articlenumber"))

#     logger.info(f"Articles missing English article number: {missing_en}")
#     logger.info(f"Articles missing French article number: {missing_fr}")
#     print(f"Articles missing English article number: {missing_en}")
#     print(f"Articles missing French article number: {missing_fr}")

#     if missing_en > 0 or missing_fr > 0:
#         # Update article numbers
#         updated = update_article_numbers(api_session)

#         # Save the updated data
#         migrate_articles_datetime = get_utc_datetime()
#         with open(f"./data/migrated_articles_{env}_{migrate_articles_datetime}_final.json", "w") as migrated_data_file:
#             json.dump(migrated_articles, migrated_data_file, indent=4)

#         logger.info(f"Final update complete. Updated {updated} article numbers.")
#         print(f"Final update complete. Updated {updated} article numbers.")

#         # Final count
#         still_missing_en = sum(1 for article in migrated_articles.values() if not article.get("en_articlenumber"))
#         still_missing_fr = sum(1 for article in migrated_articles.values()
#                              if "fr_knowledgearticleid" in article and not article.get("fr_articlenumber"))

#         if still_missing_en > 0 or still_missing_fr > 0:
#             logger.warning(f"Still missing {still_missing_en} English and {still_missing_fr} French article numbers")
#             print(f"Still missing {still_missing_en} English and {still_missing_fr} French article numbers")
#             print("These may need manual intervention or longer wait times.")
#     else:
#         logger.info("All articles have article numbers!")
#         print("All articles have article numbers!")


# Utility function to run final update if needed
# Uncomment and run if you need to update missing article numbers after migration
# final_article_number_update()

print("Migration script loaded successfully!")
print("To run migration:")
print("1. Ensure your variables.py and parameters.json are configured")
print("2. Run the script")
