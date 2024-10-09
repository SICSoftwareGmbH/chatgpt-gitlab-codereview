import os
import sys
import asyncio
import logging
from openai import AsyncOpenAI
import xml.etree.ElementTree as ET
from datetime import datetime

# Set up logging
logging.basicConfig(level=logging.INFO)

# Set up the AsyncOpenAI client
api_key = os.getenv("OPENAI_API_KEY")

if not api_key:
    logging.error("Error: OPENAI_API_KEY environment variable is not set.")
    sys.exit(1)
client = AsyncOpenAI(api_key=api_key)

# Read the content of a diff file
def read_diff_file(file_path):
    try:
        with open(file_path, 'r') as file:
            diff_content = file.read()
        return diff_content
    except Exception as e:
        logging.error(f"Error reading file {file_path}: {e}")
        return None

def create_junit_xml(results):
    test_suite = ET.Element("testsuite")
    test_suite.set("name", "Code Check Results")
    test_suite.set("tests", str(len(results)))
    test_suite.set("timestamp", datetime.now().isoformat())

    for file_name, result in results.items():
        test_case = ET.SubElement(test_suite, "testcase")
        test_case.set("name", file_name)
        test_case.set("classname", "CodeCheck")
        
        if "serious issue" in result.lower():
            failure = ET.SubElement(test_case, "failure")
            failure.set("message", "Serious issues found")
            failure.text = result
        elif "improvement" in result.lower():
            warning = ET.SubElement(test_case, "warning")
            warning.set("message", "Improvements suggested")
            warning.text = result

    tree = ET.ElementTree(test_suite)
    tree.write("code_check_results.xml", encoding="utf-8", xml_declaration=True)

# Parse the diff content
def parse_diff_content(diff_content):
    file_diffs = diff_content.split('diff --git')
    file_diffs = ['diff --git' + diff for diff in file_diffs if diff.strip()]
    
    parsed_diffs = []
    for file_diff in file_diffs:
        lines = file_diff.split('\n')
        file_name = lines[0].split()[-1].strip('b/')
        changes = '\n'.join(lines[1:])
        parsed_diffs.append((file_name, changes))
    
    return parsed_diffs

# Asynchronous function to check code changes with OpenAI API
async def check_changes_with_openai(changes, file_name):
    file_content = read_diff_file(file_name)
    prompt = f"Analyze the following code {file_content}. Important are the latest changes to the code (diff):\n\n{changes}"
    try:
        response = await client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are a code review assistant specialized in identifying potential issues and improvements in code changes. Analyze the provided diff, focusing on: 1. Serious issues that could lead to bugs, security vulnerabilities, or significant performance problems. 2. Code quality improvements, including readability, maintainability, and adherence to best practices. 3. Potential logic errors or edge cases that might have been overlooked. Provide a concise summary, clearly distinguishing between serious issues and general improvements."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=4048,
            temperature=0.5
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logging.error(f"Error communicating with OpenAI API for {file_name}: {e}")
        return None

# Main asynchronous function to iterate over the changed files
async def main(changed_files, diff_file):
    serious_issues_count = 0
    improvements_count = 0

    diff_content = read_diff_file(diff_file)
    if diff_content is None:
        logging.error("Failed to read diff file.")
        sys.exit(1)

    parsed_diffs = parse_diff_content(diff_content)
    results = {}
    for file_name, changes in parsed_diffs:
        if file_name not in changed_files:
            continue

        result = await check_changes_with_openai(changes, file_name)
        if result is None:
            continue
        results[file_name] = result
        logging.info(f"Code Review Result for {file_name}:")
        logging.info(result)

        # Count serious issues and improvements
        serious_issues = result.lower().count("serious issue")
        improvements = result.lower().count("improvement")

        serious_issues_count += serious_issues
        improvements_count += improvements

        if serious_issues > 0:
            logging.error(f"Found {serious_issues} serious issues in {file_name}.")
        if improvements > 0:
            logging.info(f"Found {improvements} improvements in {file_name}.")

    # Decide the exit code based on the number of serious issues and improvements
    logging.info(f"Total serious issues: {serious_issues_count}")
    logging.info(f"Total improvements: {improvements_count}")
    
    create_junit_xml(results)

    if serious_issues_count > 4:
        logging.error("More than 4 serious issues found. Failing the pipeline.")
        sys.exit(1)
    elif serious_issues_count > 0:
        logging.error("Some serious issues found. Exiting with status 2.")
        sys.exit(2)
    elif improvements_count > 0:
        logging.info("No serious issues found, only improvements. Exiting with status 3.")
        sys.exit(3)
    else:
        logging.info("No serious issues or improvements found. Exiting normally.")
        sys.exit(0)

# Entry point to the script
if __name__ == "__main__":
    if len(sys.argv) < 3:
        logging.error("Usage: python check_code.py <file_list> <diff_file>")
        sys.exit(1)

    changed_files = sys.argv[1].split()
    diff_file = sys.argv[2]

    # Run the main function asynchronously
    asyncio.run(main(changed_files, diff_file))