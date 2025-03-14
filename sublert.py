#!/usr/bin/env python
# coding: utf-8
# Announced and released during OWASP Seasides 2019 & NullCon.
# Huge shout out to the Indian bug bounty community for their hospitality.

import time
from config import *
import argparse
import dns.resolver
import sys
import requests
import json
import difflib
import os
import re
import subprocess
import psycopg2
from tld import get_fld
from tld.utils import update_tld_names
from termcolor import colored
import threading
# checks if python version used == 2 in order to properly handle import of Queue module depending on the version used.
is_py2 = sys.version[0] == "2"
if is_py2:
    import Queue as queue
else:
    import queue as queue

version = "1.4.7"
requests.packages.urllib3.disable_warnings()


def banner():
    print('''
                   _____       __    __          __
                  / ___/__  __/ /_  / /__  _____/ /_
                  \__ \/ / / / __ \/ / _ \/ ___/ __/
                 ___/ / /_/ / /_/ / /  __/ /  / /_
                /____/\__,_/_.___/_/\___/_/   \__/
    ''')
    print(colored("             Author: Yassine Aboukir (@yassineaboukir)", "red"))
    print(colored("                           Version: {}", "red").format(version))


def parse_args():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('-u', '--url',
                        dest="target",
                        help="Domain to monitor. E.g: yahoo.com",
                        required=False)
    parser.add_argument("-q", "--question",
                        type=string_to_bool, nargs='?',
                        const=True, default=True,
                        help="Disable user input questions")
    parser.add_argument('-d', '--delete',
                        dest="remove_domain",
                        help="Domain to remove from the monitored list. E.g: yahoo.com",
                        required=False)
    parser.add_argument('-t', '--threads',
                        dest="threads",
                        help="Number of concurrent threads to use. Default: 10",
                        type=int,
                        default=10)
    parser.add_argument('-r', '--resolve',
                        dest="resolve",
                        help="Perform DNS resolution.",
                        required=False,
                        nargs='?',
                        const="True")
    parser.add_argument('-l', '--logging',
                        dest="logging",
                        help="Enable Discord-based error logging.",
                        required=False,
                        nargs='?',
                        const="True")
    parser.add_argument('-a', '--list',
                        dest="listing",
                        help="Listing all monitored domains.",
                        required=False,
                        nargs='?',
                        const="True")
    parser.add_argument('-m', '--reset',
                        dest="reset",
                        help="Reset everything.",
                        nargs='?',
                        const="True")
    return parser.parse_args()


def domain_sanity_check(domain):  # Verify the domain name sanity
    if domain:
        try:
            domain = get_fld(domain, fix_protocol=True)
            return domain
        except:
            print(colored(
                "[!] Incorrect domain format. Please follow this format: example.com, http(s)://example.com, www.example.com", "red"))
            sys.exit(1)
    else:
        pass


def discord(data):  # posting to discord
    webhook_url = posting_webhook
    discord_data = {'content': data}
    response = requests.post(
        webhook_url,
        data=json.dumps(discord_data),
        headers={'Content-Type': 'application/json'}
    )
    if response.status_code != 204:
        error = "Request to discord returned an error {}, the response is:\n{}".format(
            response.status_code, response.text)
        errorlog(error, enable_logging)
    if discord_sleep_enabled:
        time.sleep(1)


def reset(do_reset):  # clear the monitored list of domains and remove all locally stored files
    if do_reset:
        os.system(
            "cd ./output/ && rm -f *.txt && cd .. && rm -f domains.txt && touch domains.txt")
        print(colored(
            "\n[!] Sublert was reset successfully. Please add new domains to monitor!", "red"))
        sys.exit(1)
    else:
        pass


def remove_domain(domain_to_delete):  # remove a domain from the monitored list
    new_list = []
    if domain_to_delete:
        with open("domains.txt", "r") as domains:
            for line in domains:
                line = line.replace("\n", "")
                if line in domain_to_delete:
                    os.system("rm -f ./output/{}.txt".format(line))
                    print(colored(
                        "\n[-] {} was successfully removed from the monitored list.".format(line), "green"))
                else:
                    new_list.append(line)
        os.system("rm -f domains.txt")
        with open("domains.txt", "w") as new_file:
            for i in new_list:
                new_file.write(i + "\n")
        sys.exit(1)


def domains_listing():  # list all the monitored domains
    global list_domains
    if list_domains:
        print(
            colored("\n[*] Below is the list of monitored domain names:\n", "green"))
        with open("domains.txt", "r") as monitored_list:
            for domain in monitored_list:
                print(colored("{}".format(domain.replace("\n", "")), "yellow"))
        sys.exit(1)


def errorlog(error, enable_logging):  # log errors and post them to discord channel
    if enable_logging:
        print(colored(
            "\n[!] We encountered a small issue, please check error logging Discord channel.", "red"))
        webhook_url = errorlogging_webhook
        discord_data = {'content': '```' + error + '```'}
        response = requests.post(
            webhook_url,
            data=json.dumps(discord_data),
            headers={'Content-Type': 'application/json'}
        )
        if response.status_code != 204:
            error = "Request to discord returned an error {}, the response is:\n{}".format(
                response.status_code, response.text)
            errorlog(error, enable_logging)
    else:
        pass


class cert_database(object):
    global enable_logging

    def lookup(self, domain, wildcard=True):
        subdomains = set()

        # Use subfinder to find subdomains
        try:
            command = ["subfinder", "-d", domain, "-all"]
            subdomains_output = subprocess.check_output(
                command, stderr=subprocess.STDOUT)
            subdomains_output = subdomains_output.decode("utf-8").strip()
            subdomains.update(subdomains_output.split('\n'))
        except Exception as e:
            print("An error occurred while running subfinder:", e)

        # Connect to crt.sh API to retrieve additional subdomains
        try:
            unique_domains = set()
            domain = domain.replace('%25.', '')
            conn = psycopg2.connect(
                "dbname={0} user={1} host={2}".format(DB_NAME, DB_USER, DB_HOST))
            conn.autocommit = True
            cursor = conn.cursor()
            cursor.execute(
                "SELECT ci.NAME_VALUE NAME_VALUE FROM certificate_identity ci WHERE ci.NAME_TYPE = 'dNSName' AND reverse(lower(ci.NAME_VALUE)) LIKE reverse(lower('%{}'));".format(domain))
            for result in cursor.fetchall():
                matches = re.findall(r"\'(.+?)\'", str(result))
                for subdomain in matches:
                    try:
                        if get_fld("https://" + subdomain) == domain:
                            unique_domains.add(subdomain.lower())
                    except:
                        pass
            subdomains.update(unique_domains)
        except:
            base_url = "https://crt.sh/?q={}&output=json"
            if wildcard:
                domain = "%25.{}".format(domain)
                url = base_url.format(domain)
            user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/109.0'
            # times out after 30 seconds waiting (Mainly for large datasets)
            req = requests.get(
                url, headers={'User-Agent': user_agent}, timeout=30, verify=False)
            if req.status_code == 200:
                content = req.content.decode('utf-8')
                data = json.loads(content)
                for subdomain in data:
                    subdomains.add(subdomain["name_value"].lower())

        # Filter duplicates and add to cursor
        subdomains = set(subdomains)
        for subdomain in subdomains:
            cursor.execute(
                "INSERT INTO certificate_identity (NAME_TYPE, NAME_VALUE, CERTIFICATE_ID) VALUES ('dNSName', %s, %s);",
                (subdomain, None))

        return sorted(subdomains)


def queuing():  # using the queue for multithreading purposes
    global domain_to_monitor
    global q1
    global q2
    q1 = queue.Queue(maxsize=0)
    q2 = queue.Queue(maxsize=0)
    if domain_to_monitor:
        pass
    elif os.path.getsize("domains.txt") == 0:
        print(colored(
            "[!] Please consider adding a list of domains to monitor first.", "red"))
        sys.exit(1)
    else:
        with open("domains.txt", "r") as targets:
            for line in targets:
                if line != "":
                    q1.put(line.replace('\n', ''))
                    q2.put(line.replace('\n', ''))
                else:
                    pass


def adding_new_domain(q1):  # adds a new domain to the monitoring list
    unique_list = []
    global domain_to_monitor
    global input
    if domain_to_monitor:
        # check if domains.txt exist, if not create a new one
        if not os.path.isfile('./domains.txt'):
            os.system("touch domains.txt")
        else:
            pass
        # checking domain name isn't already monitored
        with open("domains.txt", "r+") as domains:
            for line in domains:
                if domain_to_monitor == line.replace('\n', ''):
                    print(colored("[!] The domain name {} is already being monitored.".format(
                        domain_to_monitor), "red"))
                    sys.exit(1)
            response = cert_database().lookup(domain_to_monitor)
            if response:
                # saving a copy of current subdomains
                with open("./output/" + domain_to_monitor.lower() + ".txt", "a") as subdomains:
                    for subdomain in response:
                        subdomains.write(subdomain + "\n")
                with open("domains.txt", "a") as domains:  # fetching subdomains if not monitored
                    domains.write(domain_to_monitor.lower() + '\n')
                    print(colored(
                        "\n[+] Adding {} to the monitored list of domains.\n".format(domain_to_monitor), "yellow"))
                try:
                    input = raw_input  # fixes python 2.x and 3.x input keyword
                except NameError:
                    pass
                if not question:
                    sys.exit(1)
                choice = input(colored("[?] Do you wish to list subdomains found for {}? [Y]es [N]o (default: [N]) ".format(
                    domain_to_monitor), "yellow"))  # listing subdomains upon request
                if choice.upper() == "Y":
                    for subdomain in response:
                        unique_list.append(subdomain)
                    unique_list = list(set(unique_list))
                    for subdomain in unique_list:
                        print(colored(subdomain, "yellow"))
            else:
                print(colored("\n[!] Added but unfortunately, we couldn't find any subdomain for {}".format(
                    domain_to_monitor), "red"))
                sys.exit(1)
    else:  # checks if a domain is monitored but has no text file saved in ./output
        try:
            line = q1.get(timeout=10)
            if not os.path.isfile("./output/" + line.lower() + ".txt"):
                response = cert_database().lookup(line)
                if response:
                    with open("./output/" + line.lower() + ".txt", "a") as subdomains:
                        for subdomain in response:
                            subdomains.write(subdomain + "\n")
                else:
                    pass
            else:
                pass
        except queue.Empty:
            pass


# retrieves new list of subdomains and stores a temporary text file for comparaison purposes
def check_new_subdomains(q2):
    global domain_to_monitor
    global domain_to_delete
    if domain_to_monitor is None:
        if domain_to_delete is None:
            try:
                line = q2.get(timeout=10)
                print("[*] Checking {}".format(line))
                with open("./output/" + line.lower() + "_tmp.txt", "a") as subs:
                    response = cert_database().lookup(line)
                    if response:
                        for subdomain in response:
                            subs.write(subdomain + "\n")
            except queue.Empty:
                pass
    else:
        pass


# compares the temporary text file with previously stored copy to check if there are new subdomains
def compare_files_diff(domain_to_monitor):
    global enable_logging
    if domain_to_monitor is None:
        if domain_to_delete is None:
            result = []
            with open("domains.txt", "r") as targets:
                for line in targets:
                    domain_to_monitor = line.replace('\n', '')
                    try:
                        file1 = open(
                            "./output/" + domain_to_monitor.lower() + '.txt', 'r')
                        file2 = open(
                            "./output/" + domain_to_monitor.lower() + '_tmp.txt', 'r')
                        diff = difflib.ndiff(
                            file1.readlines(), file2.readlines())
                        # check if there are new items/subdomains
                        changes = [l for l in diff if l.startswith('+ ')]
                        newdiff = []
                        for c in changes:
                            c = c \
                                .replace('+ ', '') \
                                .replace('*.', '') \
                                .replace('\n', '')
                            result.append(c)
                            result = list(set(result))  # remove duplicates
                    except:
                        error = "There was an error opening one of the files: {} or {}".format(
                            domain_to_monitor + '.txt', domain_to_monitor + '_tmp.txt')
                        errorlog(error, enable_logging)
                        os.system(
                            "rm -f ./output/{}".format(line.replace('\n', '') + "_tmp.txt"))
                return (result)


def dns_resolution(new_subdomains):  # Perform DNS resolution on retrieved subdomains
    dns_results = {}
    subdomains_to_resolve = new_subdomains
    print(
        colored("\n[!] Performing DNS resolution. Please do not interrupt!", "red"))
    for domain in subdomains_to_resolve:
        domain = domain \
            .replace('+ ', '') \
            .replace('*.', '')
        dns_results[domain] = {}
        try:
            for qtype in ['A', 'CNAME']:
                dns_output = dns.resolver.query(
                    domain, qtype, raise_on_no_answer=False)
                if dns_output.rrset is None:
                    pass
                elif dns_output.rdtype == 1:
                    a_records = [str(i) for i in dns_output.rrset]
                    dns_results[domain]["A"] = a_records
                elif dns_output.rdtype == 5:
                    cname_records = [str(i) for i in dns_output.rrset]
                    dns_results[domain]["CNAME"] = cname_records
                else:
                    pass
        except dns.resolver.NXDOMAIN:
            pass
        except dns.resolver.Timeout:
            dns_results[domain]["A"] = eval('["Timed out while resolving."]')
            dns_results[domain]["CNAME"] = eval(
                '["Timed out error while resolving."]')
            pass
        except dns.exception.DNSException:
            dns_results[domain]["A"] = eval(
                '["There was an error while resolving."]')
            dns_results[domain]["CNAME"] = eval(
                '["There was an error while resolving."]')
            pass
    if dns_results:
        # Discord new subdomains with DNS ouput
        return posting_to_discord(None, True, dns_results)
    else:
        # Nothing found notification
        return posting_to_discord(None, False, None)


def at_channel():  # control discord @channel
    return ("" if at_channel_enabled else "")


# sending result to discord workplace
def posting_to_discord(result, dns_resolve, dns_output):
    global domain_to_monitor
    global new_subdomains
    if dns_resolve:
        dns_result = dns_output
        if dns_result:
            # filters non-resolving subdomains
            dns_result = {k: v for k, v in dns_result.items() if v}
            rev_url = []
            print(
                colored("\n[!] Exporting result to discord. Please do not interrupt!", "red"))
            for url in dns_result:
                url = url \
                    .replace('*.', '') \
                    .replace('+ ', '')
                rev_url.append(get_fld(url, fix_protocol=True))

            # filters non-resolving subdomains from new_subdomains list
            unique_list = list(set(new_subdomains) & set(dns_result.keys()))

            for subdomain in unique_list:
                data = "{}:new: {}".format(at_channel(), subdomain)
                discord(data)
                try:
                    if dns_result[subdomain]["A"]:
                        for i in dns_result[subdomain]["A"]:
                            data = "```A : {}```".format(i)
                            discord(data)
                except:
                    pass
                try:
                    if dns_result[subdomain]['CNAME']:
                        for i in dns_result[subdomain]['CNAME']:
                            data = "```CNAME : {}```".format(i)
                            discord(data)
                except:
                    pass
            print(colored("\n[!] Done. ", "green"))
            rev_url = list(set(rev_url))
            for url in rev_url:
                os.system("rm -f ./output/" + url.lower() + ".txt")
                os.system("mv -f ./output/" + url.lower() + "_tmp.txt " +
                          "./output/" + url.lower() + ".txt")  # save the temporary one
            # remove the remaining tmp files
            os.system("rm -f ./output/*_tmp.txt")

    elif result:
        rev_url = []
        print(
            colored("\n[!] Exporting the result to discord. Please don't interrupt!", "red"))
        for url in result:
            url = "https://" + url.replace('+ ', '')
            rev_url.append(get_fld(url))
            data = "{}:new: {}".format(at_channel(), url)
            discord(data)
        print(colored("\n[!] Done. ", "green"))
        rev_url = list(set(rev_url))

        for url in rev_url:
            os.system("rm -f ./output/" + url.lower() + ".txt")
            os.system("mv -f ./output/" + url.lower() + "_tmp.txt " +
                      "./output/" + url.lower() + ".txt")  # save the temporary one
        os.system("rm -f ./output/*_tmp.txt")  # remove the remaining tmp files

    else:
        if not domain_to_monitor:
            data = "{}:-1: We couldn't find any new valid subdomains.".format(
                at_channel())
            discord(data)
            print(colored("\n[!] Done. ", "green"))
            os.system("rm -f ./output/*_tmp.txt")
        else:
            pass


def multithreading(threads):
    global domain_to_monitor
    threads_list = []
    if not domain_to_monitor:
        # minimum threads executed equals the number of monitored domains
        num = sum(1 for line in open("domains.txt"))
        for i in range(max(threads, num)):
            if not (q1.empty() and q2.empty()):
                t1 = threading.Thread(target=adding_new_domain, args=(q1, ))
                t2 = threading.Thread(target=check_new_subdomains, args=(q2, ))
                t1.start()
                t2.start()
                threads_list.append(t1)
                threads_list.append(t2)
    else:
        adding_new_domain(domain_to_monitor)

    for t in threads_list:
        t.join()


def string_to_bool(v):
    if isinstance(v, bool):
        return v
    if v.lower() in ('yes', 'true', 't', 'y', '1'):
        return True
    elif v.lower() in ('no', 'false', 'f', 'n', '0'):
        return False
    else:
        raise argparse.ArgumentTypeError('Boolean value expected.')


if __name__ == '__main__':

    # parse arguments
    dns_resolve = parse_args().resolve
    enable_logging = parse_args().logging
    list_domains = parse_args().listing
    domain_to_monitor = domain_sanity_check(parse_args().target)
    question = parse_args().question
    domain_to_delete = domain_sanity_check(parse_args().remove_domain)
    do_reset = parse_args().reset

# execute the various functions
    banner()
    reset(do_reset)
    remove_domain(domain_to_delete)
    domains_listing()
    queuing()
    multithreading(parse_args().threads)
    new_subdomains = compare_files_diff(domain_to_monitor)

# Check if DNS resolution is checked
    if not domain_to_monitor:
        if (dns_resolve and new_subdomains):
            dns_resolution(new_subdomains)
        else:
            posting_to_discord(new_subdomains, False, None)
    else:
        pass
