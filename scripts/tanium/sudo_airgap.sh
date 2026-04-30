#!/bin/bash

# Specify the path to the text file with URLs
urlFile="urls.txt"

# Define the source folder and the root directory
sourceFolder="/tmp/source_files"
rootDirectory="/opt/Tanium/TaniumServer/http"

# Check if the source folder exists
if [ ! -d "$sourceFolder" ]; then
    echo "Source folder does not exist: $sourceFolder"
    exit 1
fi

# Read each URL from the file
while IFS= read -r url; do
    # Skip empty lines
    if [ -z "$url" ]; then
        continue
    fi

    # Remove "http://", "https://", and "www." parts from the URL
    urlPath=$(echo "$url" | sed -E 's|^https?://(www\.)?||')

    # Remove the domain part (everything before the first '/')
    urlPath=$(echo "$urlPath" | sed -E 's|^[^/]+/||')

    # Extract the directory part (everything except the file name)
    directoryPath="$rootDirectory/$urlPath"
    directoryPath=$(dirname "$directoryPath")  # Get the parent directory (without the file name)

    # Create the directory if it doesn't exist
    if [ ! -d "$directoryPath" ]; then
        mkdir -p "$directoryPath"
        echo "Created directory: $directoryPath"
    else
        echo "Directory already exists: $directoryPath"
    fi

    # Extract the file name from the URL (i.e., the last part after the last '/')
    fileName=$(basename "$url")

    # Define the source file path
    sourceFilePath="$sourceFolder/$fileName"

    # Check if the file exists in the source folder
    if [ -f "$sourceFilePath" ]; then
        # Define the destination file path (directly in the created directory)
        destinationFilePath="$directoryPath/$fileName"

        # Move the file to the created directory
        mv "$sourceFilePath" "$destinationFilePath"
        echo "Moved file '$fileName' to '$destinationFilePath'."
    else
        echo "File '$fileName' not found in the source folder."
    fi
done < "$urlFile"

echo "Directory creation and file movement complete."
