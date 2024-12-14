from datetime import datetime
import json
import re
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup
import requests

def get_email(email: str=None) -> str:
    '''
    Retrieves the email address for polite communication with CrossRef or prompts the user if 
    unavailable.
    
    Args:
    - email (str, optional): The email address. If not provided, it will be retrieved from a 
    file or requested from the user.
    
    Returns:
    str: The email address for polite communication with CrossRef.
    '''
    if email:
        return email
    
    email_file = Path('email.txt')
    if email_file.is_file():
        with open(email_file, 'rt') as fin:
            email = fin.read().strip()
    else:
        email = input('Email address (for CrossRef polite authentication): ').strip()
        with open(email_file, 'wt') as fout:
            fout.write(email)

    return email

def read_soup(r: requests.models.Response) -> list[str]:
    '''
    Parses the HTML content and extracts a list of titles from a specific section in the HTML.

    Args:
    - r (requests.models.Response): The HTTP response object containing the HTML content.

    Returns:
    list[str]: A list of titles extracted from the HTML content.
    '''
    html = r.text
    soup = BeautifulSoup(html, 'html.parser')
    peeriodical = soup.find('peeriodical')
    peeriodical_read = str(peeriodical).replace('&quot;', '"') # Convert to string
    peeriodical_read = peeriodical_read.partition('"name":')[2] # Extract section with titles

    titles = [x for x in peeriodical_read.split('"title":') if x] # Splits into list of titles

    return titles

def extract_authors(splits: list[str]) -> list[tuple[str, str]]:
    '''
    Extracts author names and their corresponding ORCIDs from a list of string splits.

    Args:
    - splits (list[str]): The list of string splits containing author information.

    Returns:
    list[tuple[str, str]]: A list of tuples where each tuple contains an author's name and their ORCID.
    '''
    author_names = [splits[m+2] for m, value in enumerate(splits) if value == 'display_name']
    author_names = [re.sub(r'\\(u[\da-fA-F]{4})', r'&\1;', name) for name in author_names] # Replace Unicode escape sequences
    author_orcids = [splits[m+2].replace('\\/', '/') for m, value in enumerate(splits) if value == 'orcid']
    authors = list(zip(author_names, author_orcids))

    return authors

def publication_to_dict(publication: str, lod: list[dict]) -> dict | None:
    '''
    Parses a single publication and extracts important values to a dictionary.

    Args:
    - publication (str): The publication data to be processed.
    - lod (list[dict]): The list of dictionaries representing previous publications.

    Returns:
    dict | None: A dictionary containing the parsed publication data, or None if the publication is invalid.
    '''
    title = publication.partition('",')[0][1:] # Pull title from between initial set of quotes
    if title == peeriodical_name: 
       return None # Not a publication
    
    # Replace selected HTML sequences in title
    title = title.replace('&lt;', '<').replace('&gt;', '>').replace('\\/', '/')
    results = {'title': re.sub(r'\\(u[\da-fA-F]{4})', r'&\1;', title)} # Replace Unicode escape sequences

    publication = publication.partition(f'{title}",')[2]
    splits = publication.split('"')

    if splits == ['']:
        return None

    journal_url = splits[splits.index('url') + 2].replace('\\/', '/')
    if journal_url in [publication['journal_url'] for publication in lod]:
        return None # Publication already exists
    
    results['journal_url'] = journal_url
    results['year'] = int(splits[splits.index('published_at') + 2])
    results['id'] = splits[splits.index('pubpeer_id') + 2]
    suffix = fr'{peeriodical_url_name}/publications/{results["id"]}'
    results['peeriodical_url'] = f'https://peeriodicals.com/peeriodical/{suffix}'
    
    if 'DOI' in splits:
        results['doi'] = splits[splits.index('DOI') - 4].replace('\\/', '/')
    if 'PubMed' in splits:
        results['PubMed'] = splits[splits.index('PubMed') - 4].replace('\\/', '/')

    updated_date = splits[splits.index('updated_at') + 2]
    results['updated'] = datetime.strptime(updated_date, '%Y-%m-%dT%H:%M:%S.000000Z')

    if 'editorial_decision' in splits:
        editorial_decision = splits[splits.index('editorial_decision') + 1]
        if 'true' in editorial_decision:
            editorial_decision = True
        results['editorial_decision'] = editorial_decision
    else: # If an editorial decision is not listed, it's considered False
        results['editorial_decision'] = False

    results['authors'] = extract_authors(splits)

    return results

def escape_cdata(text: str) -> str:
    '''
    Escapes character data within a CDATA section.

    Args:
    - text (str): The input text to be escaped.

    Returns:
    str: The escaped text.

    Raises:
    ET.ParseError: If the input text was not of the correct type. 
    '''
    try:
        if not text.startswith("<![CDATA[") and not text.endswith("]]>"):
            text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return text
    except (TypeError, AttributeError) as error:
        raise ET.ParseError(f'Failed to escape CDATA: {error}')
    
# Override the original function in the ET module
ET._escape_cdata = escape_cdata

def generate_reference(journal_abbr: str, 
                       year: str, volume: str, pages: str, 
                       doi: str
                       ) -> str:
    '''
    Generates a reference string based on the provided publication details.

    Args:
    - journal_abbr (str): The abbreviated journal name.
    - year (int): The publication year.
    - volume (str): The volume information.
    - pages (str): The page information.
    - doi (str): The DOI (Digital Object Identifier) of the publication.

    Returns:
    str: The formatted reference string based on the provided publication details.
    '''
    if pages:
        return f'<em>{journal_abbr}</em> <strong>{year}</strong>, {volume}, {pages}'
    else:
        return f'<em>{journal_abbr}</em> <strong>{year}</strong>, \
            <a href="https://doi.org/{doi}" target="_blank" rel="noopener">{doi}</a>'

def parse_message(message: dict
                  ) -> tuple[str|None, str|None, str|None, str|None]:
    '''
    Parses the message dictionary obtained from CrossRef API response.

    Args:
    - message (dict): The dictionary containing publication information.

    Returns:
    tuple: A tuple containing the parsed journal, journal abbreviation, volume, and pages.
    '''
    journal = message.get('container-title')
    journal = journal[0] if journal else None
    journal_abbr = message.get('short-container-title')
    journal_abbr = journal_abbr[0] if journal_abbr else None
    volume = message.get('volume')
    pages = message.get('page')
    pages = pages.replace('-', '&ndash;') if pages else None

    return journal, journal_abbr, volume, pages

def generate_description(publication: dict) -> str | None:
    '''
    Generates a description of the publication for the RSS feed, using the CrossRef API.

    Args:
    - publication (dict): The publication information dictionary.

    Returns:
    str: The generated description for the publication. 
    None: If the description generation fails. 
    '''
    if 'doi' not in publication:
        return None
    
    work = fr'http://api.crossref.org/works/{publication["doi"]}'
    try:
        r = requests.get(work, headers = headers_crossref, proxies=proxies, timeout = 20)
        r.raise_for_status()
    except (requests.exceptions.ConnectTimeout, requests.exceptions.HTTPError) as error:
        print(f'Request failed for doi {publication["doi"]}: {error}')

    try:
        my_dict = json.loads(r.text)
    except json.decoder.JSONDecodeError as e:
        print('Error', e)
        return None
    
    if my_dict['status'] != 'ok':
        print(f'Request for {publication["title"]} not successful. \
              Status: {my_dict["status"]}'
              )
        return None
    
    message = my_dict['message']
    journal, journal_abbr, volume, pages = parse_message(message)

    description_head = '<![CDATA[\n' # Use html
    description_tail = '\n' + '\t'*4 + ']]>\n' + '\t'*3
    reference = generate_reference(journal_abbr,
                                    publication['year'],
                                    volume,
                                    pages,
                                    publication['doi']
                                    )
    
    authors = [(', ').join([f'<a href="{i[1]}" _target="_blank" rel="noopener">{i[0]}</a>' if i[1] else i[0] for i in publication['authors']]) + '<br>']
    description = ['\t'*4 + f'<h5>{publication["title"]}</h5>',
                    '<p>',
                    f'in <em>{journal}</em><br>' if journal else '<br>',
                    *authors,
                    reference,
                    '</p>']
    description_heart = ('\n\t\t\t\t').join(description)

    description = description_head + description_heart + description_tail

    return description

def output_xml(lod: list[dict]):
    '''
    Generates an RSS feed based on the provided list of publications and writes it to 'rss.xml'.

    Args:
    - lod (list[dict]): The list of publications to be included in the RSS feed.

    Side-effects:
    Generates the RSS feed as 'rss.xml'. 
    '''
    root = ET.Element('rss')
    root.set('xmlns:atom', "http://www.w3.org/2005/Atom")
    root.set('version', '2.0')

    channel = ET.SubElement(root, 'channel')

    ET.SubElement(channel, 'title').text = peeriodical_name
    ET.SubElement(channel, 'link').text = url
    ET.SubElement(channel, 'atom:link',
                    href = '',
                    rel = 'self',
                    type = 'application/rss+xml'
                    )
    ET.SubElement(channel, 'language').text = 'en-gb'
    ET.SubElement(channel, 'category').text = 'Science'
    ET.SubElement(channel, 'description').text = peeriodical_description

    for publication in lod[::-1]:
        if publication['editorial_decision'] is True:
            title = publication['title']
            link = publication['peeriodical_url']
            guid = f'{link}?guid=0'
            pub_date = publication['updated'].strftime('%a, %d %b %Y %H:%M GMT')

            item = ET.SubElement(channel, 'item')
            ET.SubElement(item, 'title').text = title
            ET.SubElement(item, 'link').text = link
            ET.SubElement(item, 'guid').text = guid
            ET.SubElement(item, 'pubDate').text = pub_date
            
            description = generate_description(publication)
            ET.SubElement(item, 'description').text = description

    tree = ET.ElementTree(root)
    ET.indent(tree, space='\t', level=0)
    tree.write('rss.xml', xml_declaration=True, encoding='utf-8')

def run(url: str, proxies: dict) -> list[dict]:
    '''
    Executes the main workflow, including fetching data, processing it, generating an RSS feed, 
    and returning the processed data.

    Args:
    - url (str): The URL to fetch data from.
    - proxies (dict): The proxies to be used for the request.

    Returns:
    list[dict]: The processed data used to generate the RSS feed.
    '''
    r = requests.get(url, proxies=proxies)
    r.raise_for_status()
    titles = read_soup(r)
    lod = []
    for title in titles:
        result = publication_to_dict(title, lod)
        if result:
            lod.append(result)

    output_xml(lod)
    return lod

# Read in proxy file, if any
proxies = {}
proxy_file = Path('proxies.json')
if proxy_file.is_file():
    with open(proxy_file, 'rt') as fin:
        proxies = json.load(fin)
proxies = {} # Uncomment this when working locally, outside AZ network

headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/70.0.3538.77 Safari/537.36',
           'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
           'Accept-Charset': 'ISO-8859-1,utf-8;q=0.7,*;q=0.3',
           'Accept-Encoding': 'none',
           'Accept-Language': 'en-US,en;q=0.8',
           'Connection': 'keep-alive'
           }

# Retrieve user email for CrossRef authentication
try:
    email = get_email(email=f'{sys.argv[1]}@astrazeneca.com') # Uses parameter passed from cmd
except IndexError:
    email = get_email()
    
headers_crossref = {'User-Agent': 'Peeriodicals-to-RSS; mailto:{email}',
           'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
           'Accept-Charset': 'ISO-8859-1,utf-8;q=0.7,*;q=0.3',
           'Accept-Encoding': 'none',
           'Accept-Language': 'en-US,en;q=0.8',
           'Connection': 'keep-alive'
           }

peeriodical_name = 'High-Throughput Automation In R and D'
peeriodical_url_name = 'high-throughput-automation-in-rampd'
url = fr'https://peeriodicals.com/peeriodicals/{peeriodical_url_name}'
peeriodical_description = 'This journal aims to be a repository of peer-reviewed articles on the \
    use of HTE for small molecules and related topics in R&D laboratories.'

if __name__ == '__main__':
    lod = run(url, proxies)