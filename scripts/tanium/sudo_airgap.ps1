# Ensure the hosts file contains the entry "127.0.0.1 foo.bar"
$hostsFile = "C:\Windows\System32\drivers\etc\hosts"
$entry = "127.0.0.1 content.tanium.com"

# Check if the entry exists in the hosts file, if not, add it
if (-not (Select-String -Path $hostsFile -Pattern $entry)) {
    Add-Content -Path $hostsFile -Value "`r`n$entry"
    Write-Host "Added entry to hosts file."
} else {
    Write-Host "Entry already exists in hosts file."
}

# Specify the path to the text file with URLs
$urlFile = "urls.txt"

# Read in the URLs from the text file
$urls = Get-Content -Path $urlFile

# Specify the folder where the files are located before moving
$sourceFolder = "C:\temp\"
# Create the source folder if it doesn't exist
if (-not (Test-Path -Path $sourceFolder)) {
    New-Item -Path $sourceFolder -ItemType Directory
    Write-Host "Created source folder: $sourceFolder"
}

# Download each URL in the list to the source folder
foreach ($url in $urls) {
    # Ensure the URL is not empty
    if ($url.Trim()) {
        try {
            # Define the destination file name based on the URL's file name
            $fileName = [System.IO.Path]::GetFileName($url)
            $destinationPath = Join-Path -Path $sourceFolder -ChildPath $fileName

            # Download the file
            Write-Host "Downloading $url to $destinationPath..."
            Invoke-WebRequest -Uri $url -OutFile $destinationPath

            Write-Host "Downloaded: $fileName"
        } catch {
            Write-Host "Error downloading $url: $_"
        }
    }
}

# Define the root directory for the structure
$rootDirectory = "C:\Program Files\Tanium\Tanium Server\http\"

# Process each URL for directory creation and file movement
foreach ($url in $urls) {
    # Remove "http://", "https://", and "www." parts from the URL
    $url = $url -replace "^https?://(www\.)?", ""

    # Remove the domain part (everything before the first '/')
    $urlPath = $url -replace "^[^/]+/", ""

    # Define the full directory path, starting after the domain part
    $directoryPath = Join-Path -Path $rootDirectory -ChildPath $urlPath

    # Create the directory if it doesn't exist
    if (-not (Test-Path -Path $directoryPath)) {
        New-Item -Path $directoryPath -ItemType Directory
        Write-Host "Created directory: $directoryPath"
    } else {
        Write-Host "Directory already exists: $directoryPath"
    }

    # Get the file name from the URL (i.e., the last part after the last '/')
    $fileName = [System.IO.Path]::GetFileName($url)

    # Define the source file path
    $sourceFilePath = Join-Path -Path $sourceFolder -ChildPath $fileName

    # Check if the file exists in the source folder
    if (Test-Path -Path $sourceFilePath) {
        # Define the destination file path
        $destinationFilePath = Join-Path -Path $directoryPath -ChildPath $fileName

        # Move the file to the created directory
        Move-Item -Path $sourceFilePath -Destination $destinationFilePath
        Write-Host "Moved file '$fileName' to '$destinationFilePath'."
    } else {
        Write-Host "File '$fileName' not found in the source folder."
    }
}

Write-Host "File download, directory creation, and movement complete."
