# ------------------- Variables ------------------- #
$url      = "https://"    # e.g., https://tanium.company.com
$token    = "token-"                          # Session token
$jsonFile = 'export-users.json'               # Path to the JSON file with users

# ------------------- Read JSON ------------------- #
$json = Get-Content -Path $jsonFile -Raw | ConvertFrom-Json
$usersFromFile = $json.object_list.users

# ------------------- Retrieve existing users ------------------- #
try {
    $existingUsersResponse = Invoke-RestMethod `
        -Uri "$url/api/v2/users" `
        -Method GET `
        -Headers @{ Session = $token }
    $existingUsers = $existingUsersResponse.data
}
catch {
    Write-Warning "Failed to GET existing users. $_"
    return
}

Write-Host "`n----- Processing JSON Users -----`n"

foreach ($userObj in $usersFromFile) {
    $username = $userObj.name
    Write-Host "`nProcessing user: $username"

    # Check if user already exists
    $existingUser = $existingUsers | Where-Object { $_.name -eq $username }
    if (-not $existingUser) {
        Write-Host "  User '$username' does not exist; creating..."
        # Build the create payload and add group_id = 2 as requested.
        $createBody = @{
            name         = $username
            domain       = $userObj.domain
            display_name = $userObj.display_name
            group_id     = 2
        } | ConvertTo-Json
        try {
            $createResp = Invoke-RestMethod `
                -Uri "$url/api/v2/users" `
                -Method POST `
                -Body $createBody `
                -ContentType "application/json" `
                -Headers @{ Session = $token }
            Write-Host "  Created user '$($createResp.data.name)' (ID: $($createResp.data.id))"
            $userId = $createResp.data.id
            $existingUsers += [PSCustomObject]@{ id = $userId; name = $username }
        }
        catch {
            Write-Warning "  [ERROR] Could not create user '$username': $_"
            continue
        }
    }
    else {
        $userId = $existingUser.id
        Write-Host "  User '$username' already exists, ID: $userId"
    }

    # --- Assign the user to each of its defined user groups ---
    if ($userObj.user_groups -and $userObj.user_groups.Count -ge 1) {
        foreach ($groupRef in $userObj.user_groups) {
            $groupName = $groupRef.name
            Write-Host "  Assigning user '$username' to group '$groupName'"

            # Lookup the user group by retrieving the full list from /api/v2/user_groups and searching for a matching name.
            try {
                $groupsResponse = Invoke-RestMethod `
                    -Uri "$url/api/v2/user_groups" `
                    -Method GET `
                    -Headers @{ Session = $token }
                $groupsList = $groupsResponse.data
                $groupItem = $groupsList | Where-Object { $_.name -eq $groupName }
                if ($null -eq $groupItem) {
                    throw "Group '$groupName' not found in user_groups list."
                }
                $groupId = $groupItem.id
                Write-Host "      Found group '$groupName' (ID: $groupId)"
            }
            catch {
                Write-Warning "      [ERROR] Could not find group '$groupName'. $_"
                continue
            }

            # Retrieve current group details to get the existing user_list.
            try {
                $groupDetails = Invoke-RestMethod `
                    -Uri "$url/api/v2/user_groups/$groupId" `
                    -Method GET `
                    -Headers @{ Session = $token }
            }
            catch {
                Write-Warning "      [ERROR] Could not retrieve details for group '$groupName'. $_"
                continue
            }

            # Check if the user is already a member.
            $userAlreadyInGroup = $false
            if ($groupDetails.data.user_list -and $groupDetails.data.user_list.Count -gt 0) {
                if ($groupDetails.data.user_list | Where-Object { $_.id -eq $userId }) {
                    $userAlreadyInGroup = $true
                }
            }
            if ($userAlreadyInGroup) {
                Write-Host "      User '$username' is already assigned to group '$groupName', skipping."
                continue
            }

            # Build the combined user list: start with current members then add this user.
            $currentUserList = @()
            if ($groupDetails.data.user_list) {
                # Ensure user_list is an array.
                if ($groupDetails.data.user_list -isnot [System.Collections.IEnumerable]) {
                    $currentUserList = @($groupDetails.data.user_list)
                }
                else {
                    $currentUserList = $groupDetails.data.user_list
                }
            }
            # Append the new user (as an object with just the id).
            $currentUserList += @{ id = $userId }

            # Build PATCH payload. Some APIs require the group name to be sent as well.
            $patchBody = @{
                name      = $groupName
                user_list = $currentUserList
            } | ConvertTo-Json

            try {
                $assignResp = Invoke-RestMethod `
                    -Uri "$url/api/v2/user_groups/$groupId" `
                    -Method PATCH `
                    -Body $patchBody `
                    -ContentType "application/json" `
                    -Headers @{ Session = $token }
                Write-Host "      Assigned user '$username' to group '$groupName'"
            }
            catch {
                Write-Warning "      [ERROR] Failed to assign user '$username' to group '$groupName': $_"
            }
        }
    }
    else {
        Write-Host "  No user_groups defined for user '$username'."
    }
}

Write-Host "`n-- Finished processing users --"
