# MIT License

# Copyright (c) [2026] [Ifrim Denis Andrei]

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import subprocess
import sys
import threading
import time
import pandas as pd

#  valid token list 
TOKENS = pd.read_csv("tokens.csv")['tokens'].tolist()

#  index used to swap tokens
current_token_index = 0

# number of threads
# NOTE : using too many threads might trigger github to temporarily block your IP 
MAX_THREADS = 5 

# global variables for thread-safe tracking
completed_count = 0
total_prs = 0
start_time = 0
print_lock = threading.Lock()
token_lock = threading.Lock()
data_lock = threading.Lock()

#  defining possible arguments
parser = argparse.ArgumentParser(description=" Description : creates a csv file containing PR  information from the inputed links")
repo_conflicting_args = parser.add_mutually_exclusive_group()
repo_conflicting_args.add_argument(
    "-url",
    help="the url of the github repo you want to extract PR information from",
    type=str
    )
repo_conflicting_args.add_argument(
   "-file",
    help="the file containing the github repo urls",
    type=str
    )
parser.add_argument(
    "--state",
    choices = ['OPEN', 'CLOSED', 'MERGED', 'ALL'],
    default="OPEN",
    help="specify the state of the PR = OPEN , CLOSED or MERGED",
    )

args = parser.parse_args()

# function to check the rate_limit and swap to the next token 
def check_and_swap_token():
    global current_token_index
    
    # a key for the threads to swap to the next token one at the time 
    with token_lock:
        res = subprocess.run(
            ["gh", "api", "rate_limit", "--jq", ".resources.core.remaining"], 
            capture_output=True, text=True, env=os.environ
        )
        
        try:
            remaining = int(res.stdout.strip())
        except ValueError:
            remaining = 0

        # if we have less than 50 requests left, swap to the next token
        if remaining < 50 and current_token_index < len(TOKENS) - 1:
            current_token_index += 1
            os.environ["GH_TOKEN"] = TOKENS[current_token_index]
            print(f"\n Rate limit low! Swapping to Token {current_token_index + 1}...")

# function that extracts the owner and repo from urls
def repository_name_extractor(url):
    url_data = url.strip().split("/")
    owner = url_data[3]
    repo = url_data[4]
    return owner, repo

# function that fetches all valid PRs from the requested repo 
# to use them for individual PRs and to show progress so far 
def fetch_pr_numbers(owner, repo, state):
    print(f"\n Gathering all PR numbers for [{owner}/{repo}]...")

    query = [
        "gh", "api", f"repos/{owner}/{repo}/pulls",
        "--paginate", "-X", "GET",
        "-f", f"state={state.lower()}",
        "-f", "per_page=100",
        "--jq", ".[].number"
    ]
    res = subprocess.run(query, capture_output=True, text=True, encoding="utf-8", env=os.environ)
    
    if res.returncode != 0:
        print(f" Error fetching list for {owner}/{repo}: {res.stderr}")
        return []
    
    # builds the list of PR numbers 
    numbers = []
    for line in res.stdout.strip().split('\n'):
        if line.isdigit():
            numbers.append(line)

    return numbers

# function that fetches details of each individual PR 
def fetch_single_pr(num, owner, repo):
    global completed_count, total_prs, start_time

    # check the token rate_limit periodically 
    if completed_count > 0 and completed_count % 20 == 0:
        check_and_swap_token()

    cmd = [
        "gh", "api", "-X", "GET", 
        f"repos/{owner}/{repo}/pulls/{num}",
        "--jq", '{pr_number: .number, name: .title, additions: .additions, deletions: .deletions, changed_files: .changed_files, user: .user.login, repo_name: .base.repo.full_name, createdAt: .created_at, state: .state, comments: (.comments + .review_comments), mergedAt: .merged_at}'
    ]
    
    pr_data = None
    max_retries = 3

    # the threads will try 3 attempts to fetch the requested details in case the first attempt fails
    for attempt in range(max_retries):
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", env=os.environ)
        
        if res.returncode == 0:
            try:
                pr_data = json.loads(res.stdout)
                break 
            except json.JSONDecodeError:
                pass 
        else:
            stderr_lower = res.stderr.lower()
            if "rate limit exceeded" in stderr_lower or "403" in stderr_lower:
                check_and_swap_token()
                time.sleep(1) 
            
            time.sleep(2)

    if pr_data is None:
        with print_lock:
            print(f"\n FAILED to fetch PR {num} after 3 attempts. GitHub says: {res.stderr.strip()}")

    # key that is used for printing the progress in console to keep the console clean
    with print_lock:
        completed_count += 1
        if completed_count % 5 == 0 or completed_count == total_prs:
            elapsed = time.time() - start_time
            speed = completed_count / elapsed
            eta = (total_prs - completed_count) / speed if speed > 0 else 0
            
            sys.stdout.write(
                f"\rProgress: {completed_count}/{total_prs} | "
                f"Speed: {speed:.1f} PR/s | "
                f"Estimated time: {int(eta//60)}m {int(eta%60)}s    "
            )
            sys.stdout.flush()

    return pr_data


# function that handles the processing of each PR fetched and saves them
def process_repository(owner, repo, state):
    global completed_count, total_prs, start_time
    
    # fetches the numbers of the prs in the repo 
    pr_numbers = fetch_pr_numbers(owner, repo, state)

    total_prs = len(pr_numbers)
    
    if total_prs == 0:
        print(f" No {state} PRs found for {owner}/{repo}. Skipping.")
        return

    print(f" Found {total_prs} PRs in {owner}/{repo}. Fetching details for individual PRs...")
    
    completed_count = 0
    start_time = time.time()
    all_prs = []

    # using a thread pool to fetch details for each pr at the same time to boost speed
    try:
        with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
            futures = []
            for num in pr_numbers:
                future = executor.submit(fetch_single_pr, num, owner, repo)
                futures.append(future)
            
            for future in as_completed(futures):
                pr = future.result()
                if pr is not None:
                    with data_lock:
                        all_prs.append(pr)

    except KeyboardInterrupt:
        print("\n\n Stopped by user! Saving data so far...")

        filename = "pr_data.jsonl"
        print(f"\n Saving {len(all_prs)} detailed PRs to {filename}...")

        # To save in JSONL format all PRs gathered until keyboard interruption
        with open(filename, "a", encoding="utf-8") as f:
            for pr in all_prs:
                f.write(json.dumps(pr) + "\n")
        print(f" {owner}/{repo} finished in {int((time.time() - start_time)//60)} minutes.\n")

        data = pd.read_json("pr_data.jsonl", lines=True)

        # formating the csv file
        formated_csv = pd.DataFrame({   
            'PR Id' : data['pr_number'],
            'PR Name' : data['name'].astype(str).str.replace(',','_'), 
            'Repository name' : data['repo_name'],     
            'Author' : data['user'],
            'Lines altered' : data['additions'] + data['deletions'],
            'File changed' : data['changed_files'],
            'Number of comments' : data['comments'],
            'State' : data['state'],
            'Creation date' : pd.to_datetime(data['createdAt']).dt.strftime("%Y-%m-%d %H:%M:%S"),
            'Merge date' : pd.to_datetime(data['mergedAt']).dt.strftime("%Y-%m-%d %H:%M:%S"),
        })


        data = data.drop_duplicates(subset=['pr_number', 'repo_name'])
        formated_csv.insert(0, "Index", range(1, len(formated_csv) + 1))
    
        formated_csv.to_csv('formated_csv.csv', encoding='utf-8', index=False)

        sys.exit(1)

    filename = "pr_data.jsonl"
    print(f"\n Saving {len(all_prs)} detailed PRs to {filename}...")

    # To save in JSONL format
    with open(filename, "a", encoding="utf-8") as f:
        for pr in all_prs:
            f.write(json.dumps(pr) + "\n")
    print(f" {owner}/{repo} finished in {int((time.time() - start_time)//60)} minutes.\n")


def main():
    
    # setting the first token in the environment
    os.environ["GH_TOKEN"] = TOKENS[0]
    
    repos = []
    
    if args.file:
        try:
            # extracting all valid github urls
            repos_file_array = pd.read_csv(args.file)
            for i, row in enumerate(repos_file_array.itertuples(), 1):
                if "github.com" in row.url_column:
                    owner, repo = repository_name_extractor(row.url_column)
                    repos.append((owner, repo, row.state))

        except FileNotFoundError:
            print(f" Could not find file: {args.file}")
            sys.exit(1)

        for owner, repo, state in repos:
            process_repository(owner, repo, state)
            
    elif args.url:
        owner, repo = repository_name_extractor(args.url)
        repos.append((owner, repo))
        for owner, repo in repos:
            process_repository(owner, repo, args.state)


    data = pd.read_json("pr_data.jsonl", lines=True)

    # formating the csv file
    formated_csv = pd.DataFrame({   
        'PR Id' : data['pr_number'],
        'PR Name' : data['name'].astype(str).str.replace(',','_'), 
        'Repository name' : data['repo_name'],     
        'Author' : data['user'],
        'Lines altered' : data['additions'] + data['deletions'],
        'File changed' : data['changed_files'],
        'Number of comments' : data['comments'],
        'State' : data['state'],
        'Creation date' : pd.to_datetime(data['createdAt']).dt.strftime("%Y-%m-%d %H:%M:%S"),
        'Merge date' : pd.to_datetime(data['mergedAt']).dt.strftime("%Y-%m-%d %H:%M:%S"),
    })


    data = data.drop_duplicates(subset=['pr_number', 'repo_name'])
    formated_csv.insert(0, "Index", range(1, len(formated_csv) + 1))
    
    formated_csv.to_csv('formated_csv.csv', encoding='utf-8', index=False)
    

if __name__ == "__main__":
    main()