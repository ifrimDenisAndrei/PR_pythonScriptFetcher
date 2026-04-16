# PR_pythonScriptFetcher
___

## Description
  This is a python script that fetches pull requests from github repositories , saves them in a jsonl file ( in our case **pr_data.jsonl** ) and then converts it into a csv file ( in our case **pr_data_csv.csv** ).
  It implements a token swapping function to swap tokens once their rate limit is spent . The tokens must be saved in a csv file named **tokens.csv** under one column named *tokens* . The file must be placed in the same folder as the python script . Both jsonl and csv files will be generated in the current folder.
  |tokens|
  |:-----|
  |token1|
  |token2|
  |...etc|
  
## Usage
  The script accepts 3 arguments , **< -url | -file > [ --state ]**. 
### -url
  Using *-url* , the script accepts **only one** link . <br>
  The argument *--state* only accepts one of the following options : 'OPEN', 'CLOSED', 'MERGED', 'ALL' , and if not specified , its default values is OPEN . <br>
  NOTE: *--state* will only work with --url <br>
  
  Example using a single repository: <br>
  Linux : `python3 pr_fetcher.py -url <github_reposiory_link> --state ALL` <br>
  Windows : `python pr_fetcher.py -url <github_reposiory_link> --state ALL`

### -file
  Using *-file*, the script accepts a csv file containing 2 columns : *url_column* and *state*. In this method , the value for state must be specified.
  |url_column|state|
  |:---------|:----|
  |first_repo| ALL |
  | sec_repo | OPEN|
  |third_repo|CLOSED|
  |...etc....|.....|
  
  Example using multiple repositories:<br>
  Linux : `python3 pr_fetcher.py -file <csv_file>`<br>
  WIndows : `python pr_fetcher.py -file <csv_file>`

  
