#!/bin/bash

# Directory containing the files
directory="/Users/adam.durham/Downloads/tmp/metrics"

# Loop through all matching files
for file in "$directory"/metrics_*.txt; 
do
  # Extract the date and time from the filename
  if [[ $file =~ metrics_([0-9]{4}-[0-9]{2}-[0-9]{2})\ ([0-9]{6})\ \+0000\.txt ]]; then
    DATE="${BASH_REMATCH[1]}"
    TIME="${BASH_REMATCH[2]}"
    SERVER=""  # Replace with actual logic to get server name if needed
    # Construct the new filename
    new_filename="metrics_${SERVER}_${DATE} ${TIME} +0000.txt"
    # Rename the file
    mv "$file" "$directory/$new_filename"
  fi
done

echo "Renaming complete."
