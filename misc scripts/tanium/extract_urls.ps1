# Read the text from a file
$filePath = "urls.txt"
$text = Get-Content -Path $filePath

# Regex to match and capture only the https URL
$regex = "https:\/\/[a-zA-Z0-9\-\.]+\.[a-zA-Z]{2,}(\/[^\s]*)?"

# Process each line and find matches
foreach ($line in $text) {
    $match = [regex]::Match($line, $regex)
    if ($match.Success) {
        # Output only the captured URL
        Write-Host "$($match.Value)"
    }
}