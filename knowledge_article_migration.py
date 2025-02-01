# Imports and logging

import os
import re
import sys
import logging
import requests
from requests.auth import HTTPBasicAuth
import msal
from msal import ConfidentialClientApplication
import json
import base64
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
import variables
from bs4 import BeautifulSoup
import csv
import json
from jsonschema import Draft7Validator
import pprint
from datetime import datetime, timezone
from icecream import ic

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


# Freshdesk API
freshdesk_api_key = FRESHDESK_API_KEY
freshdesk_url = FRESHDESK_URL


# Dataverse API

dynamics_url = DYNAMICS_URL
scope = variables.scope

# Get secret from keyvault
key_vault_name = variables.KEY_VAULT_NAME
secret_name = SECRET_NAME
kv_uri = variables.KEY_VAULT_URI

credential = DefaultAzureCredential()
client = SecretClient(vault_url=kv_uri, credential=credential)

secret = client.get_secret(secret_name)

client_id = variables.client_id
authority = variables.authority


# Acquire access token
app = msal.ConfidentialClientApplication(
    client_id, authority=authority, client_credential=secret.value)
token_response = app.acquire_token_for_client(scopes=scope)


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


# Get images function
def get_images(article):
    global dynamics_url, headers, images, img_dict

    # Get the current UTC datetime as string
    utc_datetime_str = get_utc_datetime()

    html_content = article["description"]
    soup = BeautifulSoup(html_content, "html.parser")

    # Extract img src
    img_tags = soup.find_all("img")
    img_urls = [img['src'] for img in img_tags]

    img_dict = {}
    article_index = 0

    for img in img_urls:
        id = article["id"]
        title = article["title"]
        image_name = f"{id}_{utc_datetime_str}_{article_index}"
        local_path = f"./data/images/{image_name}.png"

        try:
            # Send a GET request to the URL
            response = requests.get(img)

            # Check if the request was successful
            if response.status_code == 200:
                # Open a file in binary write mode
                with open(local_path, "wb") as file:
                    # Write the content of the response (the image) to the file
                    file.write(response.content)
            else:
                logger.warning(f"Failed to retrieve image {image_name}.")

            # Read the image file and encode it in base64
            with open(local_path, "rb") as file:
                file_content = file.read()
                file_base64 = base64.b64encode(file_content).decode("utf-8")

            # Create a web resource with the image
            web_resource_data = {
                "name": image_name,
                "displayname": image_name,
                "description": f"Image for {title}",
                "content": file_base64,
                "webresourcetype": 5  # Type 5 for PNG images
            }
            web_resource_url = f"{dynamics_url}webresourceset"
            web_resource_response = requests.post(
                web_resource_url,
                headers=headers,
                data=json.dumps(web_resource_data)
            )

            if web_resource_response.status_code in [201, 204]:
                public_url = f"{dynamics_url}WebResources/{image_name}"
            else:
                logger.warning(
                    f"Failed to create web resource for image: {image_name}."
                )
                try:
                    logger.warning(web_resource_response.json())
                except json.JSONDecodeError:

            img_dict = {
                "article_id": id,
                "aws_url": img,
                "article_title": title,
                "local_path": local_path,
                "dynamics_image_url": public_url
            }

            # images.append(img_dict)
            images[image_name] = img_dict
            article_index += 1

        except:
            logger.warning(f"Failed to migrate image {image_name}")


# Add categories to Dynamics function

def import_categories_to_dynamics(category_set):
    global imported_categories, dynamics_categories_dict, dynamics_url, kb_folders

    imported_categories = {}

    if "access_token" in token_response:
        access_token = token_response["access_token"]

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
            'OData-MaxVersion': '4.0',
            'OData-Version': '4.0'
        }

        for category in category_set:
            category_name = category["name"]
            category_description = category["description"]
            freshdesk_category_id = category["id"]
            if "parent_folder_id" not in category:
                category_data = {
                    "title": category_name,
                    "description": category_description,
                    "revops_freshdeskcategoryid": freshdesk_category_id
                }

            elif "parent_folder_id" in category:
                parent_category_id = category["parent_folder_id"]
                category_data = {
                    "title": category_name,
                    "description": category_description,
                    "revops_freshdeskcategoryid": freshdesk_category_id,
                    "parentcategoryid@odata.bind": f'/categories({imported_categories[parent_category_id]["categoryid"]})'
                }

            categories_url = f"{dynamics_url}api/data/v9.2/categories"
            categories_response = requests.post(
                categories_url, headers=headers, data=json.dumps(category_data))
            categories_response.raise_for_status()

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

    else:
        print("Failed to acquire access token.")


# Update knowledgearticle_category function

def update_category(article_id, category_id):
    category_data = {
        "@odata.id": f"{dynamics_url}categories({category_id})"
    }

    # Make the request to update the knowledge article
    associate_url = f"{dynamics_url}knowledgearticles({article_id})/knowledgearticle_category/$ref"

    try:
        update_category_response = requests.post(
            associate_url,
            headers=headers,
            data=json.dumps(category_data)
        )
        update_category_response.raise_for_status()
        logger.info(
            f"Knowledge category updated successfully for {article_id}.")
    except requests.exceptions.HTTPError as err:
        logger.error(f"Knowledge category update failed for {article_id}.")


# Get Freshdesk categories as categories
categories_url = f"{freshdesk_url}solutions/categories/"
categories = freshdesk_get(categories_url)


# Get folders of articles from Freshdesk

kb_folders = []

for category in categories:
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
        folder_data["visibility"] = folder["visibility"]

        kb_folders.append(folder_data)

        if folder_data["sub_folders_count"] > 0:
            subfolder_id = folder_data["id"]
            subfolder_url = f"{freshdesk_url}solutions/folders/{subfolder_id}/subfolders"
            subfolders = freshdesk_get(subfolder_url)
            for subfolder in subfolders:
                subfolder_data = {}
                subfolder_data["id"] = subfolder["id"]
                subfolder_data["name"] = subfolder["name"]
                subfolder_data["description"] = subfolder["description"]
                subfolder_data["articles_count"] = subfolder["articles_count"]
                subfolder_data["sub_folders_count"] = subfolder["sub_folders_count"]
                subfolder_data["parent_folder_id"] = subfolder["parent_folder_id"]
                subfolder_data["visibility"] = subfolder["visibility"]

                kb_folders.append(subfolder_data)


# Write Freshdesk folder data to CSV
folder_query_datetime = get_utc_datetime()
csv_file = f"./data/freshdesk_folders_{folder_query_datetime}.csv"
header = ["id", "name", "description", "articles_count",
          "sub_folders_count", "parent_folder_id", "visibility"]

with open(csv_file, "w", newline="") as freshdesk_folders:
    writer = csv.DictWriter(freshdesk_folders, fieldnames=header)
    writer.writeheader()
    writer.writerows(kb_folders)


# Get categories from Dynamics

global dynamics_categories_dict

# Acquire access token
app = msal.ConfidentialClientApplication(
    client_id, authority=authority, client_credential=secret.value)
token_response = app.acquire_token_for_client(scopes=scope)

dynamics_categories_url = f"{dynamics_url}api/data/v9.2/categories"

if "access_token" in token_response:
    access_token = token_response["access_token"]

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
        "OData-MaxVersion": "4.0",
        "OData-Version": "4.0",
        "Accept": "application/json"
    }

    dynamics_categories_response = requests.get(
        dynamics_categories_url, headers=headers)

    if dynamics_categories_response.status_code == 200:
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

        print(dynamics_categories_dict)

    else:
        logger.warning(f"Failed to get categories.")
        print(
            f"Failed to get categories. Status code: {dynamics_categories_response.status_code}")


# Save categories
env = re.search(r"-(.*?).crm3", dynamics_url).group(1)

dyn_category_query_datetime = get_utc_datetime()
with open(f"./data/imported_categories_{dyn_category_query_datetime}_{env}_env.json", "w") as json_file:
    json.dump(dynamics_categories_dict, json_file)


# Add categories to dynamics

import_categories_prompt = input("Import Freshdesk categories? ")
if import_categories_prompt.lower() == "y":
    import_categories_to_dynamics(categories)
    import_categories_to_dynamics(kb_folders)

else:
    print("No categories were added.")
    imported_categories = dynamics_categories_dict


# Check for missing folders

missing_folders = []

for folder in kb_folders:
    if folder["id"] not in imported_categories:
        missing_folders.append(folder["id"])

if missing_folders:
    ic(missing_folders)
    sys.exit("Missing folders in Dynamics")


# Get articles from Freshdesk and save locally

articles = []
article_download_datetime = get_utc_datetime()

for category in kb_folders:

    freshdesk_category_id = category["id"]
    dynamics_category_id = imported_categories[freshdesk_category_id]["categoryid"]
    category_visibility = category["visibility"]
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


# Get languages

languages_url = f"{dynamics_url}languagelocale"

if "access_token" in token_response:
    access_token = token_response["access_token"]
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
        'OData-MaxVersion': '4.0',
        'OData-Version': '4.0',
        "Accept": "application/json"
    }

    # Make the GET request
    response = requests.get(languages_url, headers=headers)

    # Check the response
    if response.status_code == 200:
        languages = response.json().get('value', [])
        language_dict = {}
        for language in languages:
            language_dict[language['name']] = language['languagelocaleid']
    else:
        logger.error(
            f"Failed to retrieve languages. Status code: {response.status_code}"
        )
        logger.error(response.json())


# Migrate Freshdesk articles to Dataverse

# Acquire access token
app = msal.ConfidentialClientApplication(
    client_id, authority=authority, client_credential=secret.value)
token_response = app.acquire_token_for_client(scopes=scope)

if "access_token" in token_response:
    access_token = token_response["access_token"]
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
        "OData-MaxVersion": "4.0",
        "OData-Version": "4.0",
        "Accept": "application/json"
    }

    kb_url = f"{dynamics_url}knowledgearticles"
    migrated_articles = {}
    migrate_articles_datetime = get_utc_datetime()
    article_count = 1

    for article in articles:
        images = {}
        get_images(article)

        # Parse the HTML content
        html_content = article["description"]
        soup = BeautifulSoup(html_content, 'html.parser')

        # Iterate over each item in the dictionary
        for key, value in images.items():
            aws_url = value['aws_url']
            dynamics_image_url = value['dynamics_image_url']

            # Find all <img> tags with the aws_url as src and replace it with dynamics_image_url
            for img in soup.find_all('img', src=aws_url):
                img['src'] = dynamics_image_url

        # Write article to dynamics
        freshdesk_article_id = int(article["id"])
        article_title = article["title"]
        state_code = 3 if article["status"] == 2 else 0
        status_code = 7 if article["status"] == 2 else 2

        article_data = {
            "title": article_title,
            "revops_freshdeskarticleid": freshdesk_article_id,
            "content": f"{soup}",  # HTML with new Dynamics URLs
            "isinternal": article["dynamics_isinternal"],
            "publishon": article["created_at"],
        }

        try:
            dynamics_article_response = requests.post(
                kb_url, headers=headers, data=json.dumps(article_data)
            )
            dynamics_article_response.raise_for_status()
        except requests.exceptions.HTTPError as err:
            logger.error(f"HTTP error occurred: {err}")
            logger.error(
                f"Response content: {dynamics_article_response.content}"
            )
        except Exception as err:
            logger.error(f"Other error occurred: {err}")

        if dynamics_article_response.status_code in [201, 204]:
            logger.info(
                f"Knowledge article created successfully for {freshdesk_article_id}."
            )
            print(
                f"Knowledge article created successfully for {freshdesk_article_id} - Count: {article_count}.")
            article_count += 1

            dynamics_knowledgearticleid = dynamics_article_response.json()[
                "knowledgearticleid"]

            migrated_articles[freshdesk_article_id] = {
                "en_knowledgearticleid": dynamics_knowledgearticleid,
                "en_title": article_title
            }

            # Update knowledgearticle category
            dynamics_category_id = article["dynamics_category_id"]
            update_category(dynamics_knowledgearticleid, dynamics_category_id)

            # Check for French article in Freshdesk
            try:
                french_translation_url = f"{freshdesk_url}solutions/articles/{freshdesk_article_id}/fr"
                french_translation = freshdesk_get(french_translation_url)
                logger.info(
                    f"French article found for {freshdesk_article_id}.")

                # Get fr-ca GUID
                fr_ca_languagelocaleid = language_dict["French - Canada"]

                translation_data = {
                    "Source": {
                        "@odata.type": "Microsoft.Dynamics.CRM.knowledgearticle",
                        "knowledgearticleid": dynamics_knowledgearticleid
                    },
                    "Language": {
                        "@odata.type": "Microsoft.Dynamics.CRM.languagelocale",
                        "languagelocaleid": fr_ca_languagelocaleid
                    },
                    "IsMajor": True
                }

                if french_translation:
                    # CreateKnowledgeArticleTranslation
                    create_translation_url = f"{dynamics_url}CreateKnowledgeArticleTranslation"

                    try:
                        translation_response = requests.post(
                            create_translation_url, headers=headers, data=json.dumps(translation_data))
                        translation_response.raise_for_status()
                        logger.info(
                            f"French translation created for {freshdesk_article_id}.")

                        # Update French translation
                        fr_content = french_translation["description"]
                        fr_title = french_translation["title"]
                        translated_article_id = translation_response.json()[
                            "knowledgearticleid"]
                        fr_article_url = f"{dynamics_url}knowledgearticles({translated_article_id})"

                        french_data = {
                            "content": fr_content,
                            "title": fr_title
                        }

                        try:
                            update_fr_content_response = requests.patch(
                                fr_article_url, headers=headers, json=french_data)
                            update_fr_content_response.raise_for_status()
                            logger.info(
                                f"French content updated for {freshdesk_article_id}.")

                            migrated_articles[freshdesk_article_id].update({
                                "fr_knowledgearticleid": translated_article_id,
                                "fr_title": fr_title
                            })

                        except:
                            logger.warning(
                                f"French article update failed for {freshdesk_article_id}.")

                        # Update category on translated article
                        update_category(translated_article_id,
                                        dynamics_category_id)

                    except requests.exceptions.HTTPError as err:
                        print(f'Error: {err.translation_response.content}')

            except:
                logger.warning(
                    f"No French article found for {freshdesk_article_id}."
                )

        else:
            logging.error(
                f"An error occurred: {dynamics_article_response.content}"
            )
            try:
                print(dynamics_article_response.json())
            except json.JSONDecodeError:
                print("No JSON response body.")

else:
    print("Failed to acquire access token.")

# Save migrated articles locally
migrate_articles_datetime = get_utc_datetime()

with open(f"./data/migrated_articles_{migrate_articles_datetime}.json", "w") as migrated_data_file:
    json.dump(migrated_articles, migrated_data_file, indent=4)

print("Migrated article data saved.")
