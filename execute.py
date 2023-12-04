from datetime import datetime
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup
import requests

def get_email(email=None):
    ''' Retrieves email address for polite communication with CrossRef - or asks user if unavailable.
        Alternatively, pass a kwarg directly or from the command line. '''

    if email:
        return email
    filename = 'email.txt'
    if os.path.isfile(filename):
        with open(filename, 'rt') as fin:
            email = fin.read()
    else:
        email = input('Email address (for CrossRef polite authentication): ')
        with open(filename, 'tw') as fout:
            fout.write(email)

    return email

def read_soup(r) -> list:
    ''' Reads in the html and returns a list of titles from a single line in the html'''
    
    html = r.text
    soup = BeautifulSoup(html, 'html.parser')
    peeriodical = soup.find('peeriodical')
    peeriodical_read = str(peeriodical).replace('&quot;', '"') # -> str
    peeriodical_read = peeriodical_read.partition('"name":')[2]

    titles = [x for x in peeriodical_read.split('"title":')]

    return titles
    
def publication_to_dict(publication: str) -> dict:
    ''' Reads a single publication and converts important values to a dictionary '''
    global lod
    
    title = publication.partition('",')[0][1:] # Pull title from between initial set of quotes
    if title == peeriodical_name: 
       return None # Not a publication
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
    else: # If an editorial decision is not listed, I *think* that means it's false... 
        results['editorial_decision'] = False

    author_names = [splits[m+2] for m, value in enumerate(splits) if value == 'display_name']
    author_names = [re.sub(r'\\(u[\da-fA-F]{4})', r'&\1;', name) for name in author_names] # Replace Unicode escape sequences
    author_orcids = [splits[m+2].replace('\\/', '/') for m, value in enumerate(splits) if value == 'orcid']
    results['authors'] = list(zip(author_names, author_orcids))

    return results

def return_from_message(message, key):
    if key in message:
        return message[key]
    else:
        return None

def escape_cdata(text):
    # escape character data
    try:
        if not text.startswith("<![CDATA[") and not text.endswith("]]>"):
            if "&" in text:
                text = text.replace("&", "&amp;")
            if "<" in text:
                text = text.replace("<", "&lt;")
            if ">" in text:
                text = text.replace(">", "&gt;")
        return text
    except (TypeError, AttributeError):
        ET._raise_serialization_error(text)
ET._escape_cdata = escape_cdata

def generate_reference(journal_abbr, year, volume, pages, doi):
    if pages:
        return (f'<em>{journal_abbr}</em> '
                f'<strong>{year}</strong>, '
                f'{volume}, {pages}')
    else:
        return (f'<em>{journal_abbr}</em> '
                f'<strong>{year}</strong>, '
                f'<a href="https://doi.org/{doi}" target="_blank" ref="noopener">{doi}</a>')

def generate_description(publication: dict):
    ''' Generates a description of the publication for the RSS feed, using the CrossRef API '''

    if 'doi' in publication:
        work = fr'http://api.crossref.org/works/{publication["doi"]}'
        try:
            r = requests.get(work, headers = headers_crossref, proxies=proxies, timeout = 20)
        except requests.exceptions.ConnectTimeout:
            sleep_time = 10
            print(f'Pausing for {sleep_time} seconds')
            time.sleep(sleep_time)
            r = requests.get(work, headers = headers_crossref, proxies=proxies, timeout = 20)
        try:
            my_dict = json.loads(r.text)
        except json.decoder.JSONDecodeError as e:
            print('Error', e)
            return None
        journal, journal_abbr, volume, pages = [None] * 4 # Default
        
        if my_dict['status'] == 'ok':
            message = my_dict['message']
            journal = return_from_message(message, 'container-title')
            if journal:
                journal = journal[0]
            journal_abbr = return_from_message(message, 'short-container-title')
            if journal_abbr:
                journal_abbr = journal_abbr[0]
                if not journal:
                    journal = journal_abbr
            else:
                journal_abbr = journal
            volume = return_from_message(message, 'volume')
            pages = return_from_message(message, 'page')
            if pages:
                pages = pages.replace('-', '&ndash;')
            
        else:
            print(f'Request for {publication["title"]} not formed. \
                  Status: {publication["status"]}')
            return None

        description_head = '<![CDATA[\n' # Use html
        description_tail = '\n' + '\t'*4 + ']]>\n' + '\t'*3
        reference = generate_reference(journal_abbr,
                                       publication['year'],
                                       volume,
                                       pages,
                                       publication['doi']
                                       )
        
        description = ['\t'*4 + f'<h5>{publication["title"]}</h5>',
                       '<p>',
                       f'in <em>{journal}</em><br>' if journal else '<br>'
                       ] + \
                       [(', ').join([f'<a href="{i[1]}" _target="_blank" rel="noopener">{i[0]}</a>' if i[1] else i[0] for i in publication['authors']]) + '<br>'] + \
                       [reference,
                        '</p>']
        description_heart = ('\n\t\t\t\t').join(description)

        description = description_head + description_heart + description_tail

    return description

def output_xml(lod: list):
    ''' Outputs the RSS feed as 'rss.xml' '''
    
    root = ET.Element('rss')
    root.set('xmlns:atom', "http://www.w3.org/2005/Atom")
    root.set('version', '2.0')

    channel = ET.SubElement(root, 'channel')

    channel_title = ET.SubElement(channel, 'title').text = peeriodical_name
    channel_link = ET.SubElement(channel, 'link').text = url
    channel_atomlink = ET.SubElement(channel, 'atom:link',
                                     href = '',
                                     rel = 'self',
                                     type = 'application/rss+xml')
    channel_language = ET.SubElement(channel, 'language').text = 'en-gb'
    channel_category = ET.SubElement(channel, 'category').text = 'Science'
    channel_description = ET.SubElement(channel, 'description').text = peeriodical_description

    for publication in lod[::-1]:
        if publication['editorial_decision'] is True:
            title = publication['title']
##            print(title) # for debugging
            link = publication['peeriodical_url']
            guid = f'{link}?guid=0'
            pubDate = publication['updated'].strftime('%a, %d %b %Y %H:%M GMT')

            item = ET.SubElement(channel, 'item')
            item_title = ET.SubElement(item, 'title').text = title
            item_link = ET.SubElement(item, 'link').text = link
            item_guid = ET.SubElement(item, 'guid').text = guid
            item_pubDate = ET.SubElement(item, 'pubDate').text = pubDate
            
            description = generate_description(publication)
            item_description = ET.SubElement(item, 'description').text = description

    tree = ET.ElementTree(root)
    ET.indent(tree, space='\t', level=0)
    tree.write('rss.xml', xml_declaration=True, encoding='utf-8')

# Read in proxy file, if any
proxies = {}
if os.path.isfile('proxies.txt'):
    with open('proxies.txt', 'rt') as fin:
        for line in fin.readlines():
            k, v = line.split(': ')
            proxies[k] = v.strip()

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
peeriodical_description = 'This journal aims to be a repository of peer-reviewed articles on the use of HTE for small molecules and related topics in R&D laboratories.'

r = requests.get(url, proxies=proxies)
if r.status_code == 200:
    lod = []
    titles = read_soup(r)
    for title in titles:
        result = publication_to_dict(title)
        if result:
            lod.append(result)

    if lod:
        pass
else:
    print(r.status_code, 'Page not found')
    raise

output_xml(lod)
