
import json
import os
import sys
import time

import arrow
import requests

from bs4 import BeautifulSoup

# Python 3 script to Scrape/Spider for Azure PDF documentation.
# Chris Joakim, Microsoft, 2017/03/05


# This class attempts to define all relevant configuration in one place.

class AzdocConfig:

    def __init__(self):
        self.root_url = 'http://azureplatform.azurewebsites.net/en-us/'
        self.pdf_base = 'https://opbuildstorageprod.blob.core.windows.net/output-pdf-files/en-us/Azure.azure-documents/live/'
        self.out_dir  = 'out'
        self.pdf_dir  = 'pdf'
        self.max_docs = 100
        self.debug    = False


# This class does the actual web scraping and curl script generation,
# using the above AzdocConfig values.

class AzdocUtil:

    def __init__(self):
        self.config   = AzdocConfig()
        self.root_url = self.config.root_url
        self.pdf_base = self.config.pdf_base
        self.out_dir  = self.config.out_dir
        self.pdf_dir  = self.config.pdf_dir
        self.max_docs = self.config.max_docs
        self.debug    = self.config.debug
        self.doc_urls = list()
        self.pdf_urls = dict()

    def scrape(self):
        print('AzdocUtil.scrape...')
        self.get_parse_root_page()
        self.get_parse_doc_urls()
        self.gen_curl_pdfs_script('bash')
        self.gen_curl_pdfs_script('powershell')

    def inventory(self, user):
        print('AzdocUtil.inventory for user: {}'.format(user))
        pdf_files = list()
        utc   = arrow.utcnow()
        local = utc.to('America/New_York')
        for root, dirnames, filenames in os.walk(self.pdf_dir):
            for basename in filenames:
                if basename.endswith('.pdf'):
                    entry = dict()
                    path  = "{}/{}".format(root, basename)
                    stats = os.stat(path)
                    entry['path']  = path
                    entry['base']  = basename
                    entry['size']  = stats.st_size
                    entry['epoch'] = stats.st_ctime
                    entry['date']  = arrow.get(stats.st_ctime).format('YYYY-MM-DD HH:mm:ss ZZ')
                    pdf_files.append(entry)

        lines = list()
        lines.append(json.dumps(pdf_files, sort_keys=True, indent=2))
        d = local.format('YYYY-MM-DD').replace('-','').strip()
        h = local.format('HH:mm').replace(':','').strip()
        outfile = "{}/inventory-{}-{}-{}.json".format('data', user, d, h)
        self.write_lines(lines, outfile)

    def diff(self, tolerance, file1, file2):
        print('AzdocUtil.diff...')
        inv1  = self.read_parse_json_file(file1)
        inv2  = self.read_parse_json_file(file2)
        print('inventory files loaded; size1: {} size2: {}'.format(len(inv1), len(inv2)))
        self.names   = dict()
        self.entries = dict()
        self.collect_inventory_entries('inventory1', file1)
        self.collect_inventory_entries('inventory2', file2)
        sorted_names = sorted(self.names.keys())
        for name in sorted_names:
            key1 = self.inventory_key('inventory1', name)
            key2 = self.inventory_key('inventory2', name)
            size1, size2 = None, None
            if key1 in self.entries:
                size1 = int(self.entries[key1]['size'])
            else:
                print("absent in inventory1: {}".format(key1))
            if key2 in self.entries:
                size2 = int(self.entries[key2]['size'])
            else:
                print("absent in inventory2: {}".format(key2))
            if size1 and size2:
                size_diff = abs(size1 - size2)
                if size_diff > tolerance:
                    print('filesize difference of {} in {}'.format(size_diff, name))

    def collect_inventory_entries(self, inventory_name, json_inventory_file):
        inv = self.read_parse_json_file(json_inventory_file)

        for idx, entry in enumerate(inv):
            name = entry['base']
            size = int(entry['size'])
            key  = self.inventory_key(inventory_name, name)
            self.names[name] = name
            self.entries[key] = entry

    def inventory_key(self, inventory_name, name):
        return '{} {}'.format(inventory_name, name)

    def get_parse_root_page(self):
        print('get_parse_root_page start')
        f  = self.txt_outfile('root')
        r  = self.get(self.root_url, f);
        bs = BeautifulSoup(r.text, "html.parser")
        links = bs.find_all("a")
        for link in links:
            try:
                href = link['href']
                text = '{}'.format(link.get_text()).strip()
                if href:
                    if text == 'Documentation':
                        self.doc_urls.append(href)
            except:
                pass
        print('get_parse_root_page complete; count: {}'.format(len(self.doc_urls)))

    def get_parse_doc_urls(self):
        for idx, doc_url in enumerate(self.doc_urls):
            if idx < self.max_docs:
                name = doc_url.split('/')[-2]
                f  = self.txt_outfile(name)
                r  = self.get(doc_url, f)
                lines = r.text.split('\n')
                for line_idx, line in enumerate(lines):
                    if 'pdf_url_template' in line:
                        name = self.parse_pdf_url_template_name(line)
                        if name:
                            self.pdf_urls[name] = self.pdf_url(name)

    def pdf_url(self, name):
        return self.pdf_base + name

    def gen_curl_pdfs_script(self, shell_name):
        lines   = list()
        outfile = None

        if shell_name == 'bash':
            lines.append('#!/bin/bash\n\n')
            outfile = 'azdoc_curl_pdfs.sh'
        else:
            outfile = 'azdoc_curl_pdfs.ps1'

        lines.append("# Chris Joakim, Microsoft\n")
        lines.append("# Generated on {}\n".format(self.current_timestamp()))

        for idx, name in enumerate(sorted(self.pdf_urls.keys())):
            url = self.pdf_urls[name]
            lines.append("\n")
            lines.append("echo 'fetching: {} ...'\n".format(url))
            if shell_name == 'bash':
                lines.append("curl {} > {}/azdoc-{}\n".format(url, self.pdf_dir, name))
            else:
                lines.append("curl {} -OutFile {}/azdoc-{}\n".format(url, self.pdf_dir, name))
        lines.append('\necho "done"\n')
        self.write_lines(lines, outfile)

    def get(self, url, f):
        time.sleep(0.5)  # be nice to the web server; throttle requests to it
        if self.debug:
            print("get {} -> {}".format(url, f))
        else:
            print("get {}".format(url))
        r = requests.get(url)
        if self.debug:
            self.capture_response(f)
        return r

    def capture_response(self, f):
        with open(f, 'wt') as out:
            out.write("url:          {}\n".format(self.u))
            out.write("status_code:  {}\n".format(self.r.status_code))
            out.write("content-type: {}\n".format(self.r.headers['content-type']))
            out.write("text:\n\n{}\n".format(self.r.text))
        print("{} {} {}".format(self.r.status_code, self.u, len(self.r.text)))

    def parse_pdf_url_template_name(self, line):
        # In lines that look like this:
        #   <meta name="pdf_url_template" content="https://docs.microsoft.com/pdfstore/en-us/Azure.azure-documents/{branchName}/virtual-machines.pdf">
        # Return this:
        #   virtual-machines.pdf
        if line:
            s = line.replace('">', '  ')
            s = s.replace("'", " ")
            n = s.split('/')[-1]
            if '.pdf' in n:
                return n.strip()
        return None

    def txt_outfile(self, base):
        return '{}/{}-{}.txt'.format(self.out_dir, base, self.epoch())

    def current_timestamp(self):
        return arrow.utcnow().format('dddd YYYY-MM-DD')

    def epoch(self):
        return time.time()

    def read_parse_json_file(self, infile):
        with open(infile) as f:
            return json.loads(f.read())

    def write_lines(self, lines, outfile):
        with open(outfile, "w", newline="\n") as out:
            for line in lines:
                out.write(line)
            print('file written: {}'.format(outfile))


if __name__ == "__main__":

    if len(sys.argv) > 1:
        func = sys.argv[1].lower()

        if func == 'scrape':
            s = AzdocUtil()
            s.scrape()

        elif func == 'inventory':
            user = sys.argv[2].lower()
            s = AzdocUtil()
            s.inventory(user)

        elif func == 'diff':
            tolerance = int(sys.argv[2])
            file1 = sys.argv[3]
            file2 = sys.argv[4]
            s = AzdocUtil()
            s.diff(tolerance, file1, file2)

        else:
            print("Unknown function: {}".format(func))
    else:
        print("Invalid command-line args")