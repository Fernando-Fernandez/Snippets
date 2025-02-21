#!/usr/bin/env python3
import os
import sys
import glob
import openai
import argparse

# USAGE:  navigate to a separate folder and run  
# python3 ../../explain.py --folder ../../../force-app/main/default/triggers --filetype "*.trigger" --prompt-file triggerPrompt.txt --replace-word GEICO

# 1) Set your OpenAI API key via environment variable:  export OPENAI_API_KEY="sk-..."
openai.api_key = os.getenv("OPENAI_API_KEY")

def read_prompt_from_file(prompt_file):
    """Read prompt text from a file."""
    try:
        with open(prompt_file, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception as e:
        print(f"Error reading prompt file '{prompt_file}': {e}")
        sys.exit(1)

def get_files_recursive(folder, filetype):
    """Get files from folder and one level of subfolders if none found in main folder."""
    # First try the main folder
    target_files = glob.glob(os.path.join(folder, filetype))
    
    # If no files found in main folder, check subfolders
    if not target_files:
        print(f"No {filetype} files found in {folder}, checking subfolders...")
        for subdir in next(os.walk(folder))[1]:  # [1] gives directories
            subfolder_path = os.path.join(folder, subdir)
            target_files.extend(glob.glob(os.path.join(subfolder_path, filetype)))
    
    return target_files

def main():
    # Set up argument parser
    parser = argparse.ArgumentParser(
        description="Analyze Apex class files using OpenAI"
    )
    parser.add_argument(
        "--folder",
        default=".",
        help="Path to folder containing target files (default: current directory)"
    )
    parser.add_argument(
        "--filetype",
        default="*.cls",
        help="Filetype mask (e.g., '*.cls') (default: '*.cls')"
    )
    parser.add_argument(
        "--prompt-file",
        default=None,
        help="Path to text file containing the prompt"
    )
    parser.add_argument(
        "--replace-word",
        default=None,
        help="Word to replace with 'CompanyName' in the code before analysis"
    )
    
    args = parser.parse_args()

    # Verify folder exists
    if not os.path.isdir(args.folder):
        print(f"Error: Folder '{args.folder}' does not exist.")
        sys.exit(1)

    # Get default prompt if no prompt file is specified
    if args.prompt_file:
        base_prompt = read_prompt_from_file(args.prompt_file)
    else:
        base_prompt = (
            "Please explain the purpose of this Apex class and what other "
            "classes and objects it interacts with."
        )

    # Find all files matching the filetype mask
    target_files = get_files_recursive(args.folder, args.filetype)

    if not target_files:
        print(f"No {args.filetype} files found in {args.folder} or its immediate subfolders.")
        return

    # Get current working directory (execution folder)
    execution_folder = os.getcwd()

    for file_path in target_files:
        # Read the file content
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                code_content = f.read()

            # Replace the specified word with "CompanyName" if provided
            if args.replace_word:
                code_content = code_content.replace(args.replace_word, "CompanyName")

            # Build the prompt with the code
            prompt = (
                f"{base_prompt}\n\n"
                "=== CODE BEGIN ===\n"
                f"{code_content}\n"
                "=== CODE END ==="
            )

            # Make request to OpenAI
            response = openai.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0  # More "objective" style
            )
            explanation = response.choices[0].message.content.strip()

            # Write the explanation to a .txt file in the execution folder
            file_name = os.path.basename(file_path)  # Get just the filename
            base_name = os.path.splitext(file_name)[0]  # Remove extension
            txt_file_path = os.path.join(execution_folder, f"{base_name}.txt")

            with open(txt_file_path, "w", encoding="utf-8") as out_f:
                out_f.write(explanation)

            print(f"Wrote explanation to {txt_file_path}")

        except Exception as e:
            print(f"Error while processing '{file_path}': {e}")

if __name__ == "__main__":
    # Check if API key is set
    if not openai.api_key:
        print("Error: OPENAI_API_KEY environment variable not set.")
        sys.exit(1)
    main()
