# ------------------- Variables ------------------- #
$url      = "https://tanium.lab.amd-e.com"   # e.g., https://tanium.company.com
$token    = "token-"           # Session token
$jsonFile = 'export-user_groups.json'       # Path to the JSON file

# ------------------- Read JSON ------------------- #
$json      = Get-Content -Path $jsonFile -Raw | ConvertFrom-Json
$userGroupsFromFile = $json.object_list.user_groups

try {
    # 1) Retrieve existing user groups
    $existingGroupsResponse = Invoke-RestMethod `
        -Uri "$url/api/v2/user_groups" `
        -Method GET `
        -Headers @{ Session = $token }

    $existingGroups = $existingGroupsResponse.data
}
catch {
    Write-Warning "Failed to GET existing user groups. $_"
    return
}

Write-Host "`n----- Processing JSON User Groups -----`n"

foreach ($groupFromJson in $userGroupsFromFile) {
    $groupName = $groupFromJson.name
    Write-Host "`nUser Group (from JSON): $groupName"

    #
    # --- STEP 0: Convert the first "content_set_roles" name => single role ID ---
    #
    [int]$singleRoleId = 0
    if ($groupFromJson.content_set_roles -and $groupFromJson.content_set_roles.Count -ge 1) {
        # We'll take the *first* role from content_set_roles
        $roleName = $groupFromJson.content_set_roles[0].name
        try {
            $encodedRoleName = [System.Uri]::EscapeDataString($roleName)
            $roleLookup = Invoke-RestMethod `
                -Uri "$url/api/v2/content_set_roles/by-name/$encodedRoleName" `
                -Method GET `
                -Headers @{ Session = $token }

            $singleRoleId = $roleLookup.data.id
            Write-Host "  + Found role name '$roleName' => ID $singleRoleId"
        }
        catch {
            Write-Warning "  [ERROR] Could not find role '$roleName'. $_"
        }
    }
    else {
        Write-Host "  --> No content_set_roles in JSON or it's empty."
    }

    #
    # --- STEP A: Ensure user group exists ---
    #
    $matchingGroup = $existingGroups | Where-Object { $_.name -eq $groupName }
    if (-not $matchingGroup) {
        Write-Host "  Group '$groupName' doesn't exist; creating..."

        $createBody = @{ name = $groupName } | ConvertTo-Json
        try {
            $createResp = Invoke-RestMethod `
                -Uri "$url/api/v2/user_groups" `
                -Method POST `
                -Body $createBody `
                -ContentType "application/json" `
                -Headers @{ Session = $token }

            Write-Host "    Created user group '$($createResp.data.name)' (ID: $($createResp.data.id))"

            $newGroupObj = [PSCustomObject]@{
                id   = $createResp.data.id
                name = $createResp.data.name
            }
            $existingGroups += $newGroupObj
            $matchingGroup   = $newGroupObj

            Start-Sleep -Seconds 3
        }
        catch {
            Write-Warning "    [ERROR] Could not create user group '$groupName': $_"
            continue
        }
    }

    $userGroupId = $matchingGroup.id

    #
    # --- STEP B: Compute final group ID (parent/sub-group logic) ---
    #
    [int]$finalGroupId = 0
    if ($groupFromJson.group) {
        $parentGroupObj = $groupFromJson.group
        $parentText     = $parentGroupObj.text
        $subs           = $parentGroupObj.sub_groups

        if ($subs -and $subs.Count -ge 1) {
            $firstSub = $subs[0]
            $firstSubHasText = $false
            if ($firstSub -and $null -ne $firstSub.text -and $firstSub.text -ne "") {
                $firstSubHasText = $true
            }

            if ($firstSubHasText) {
                $firstSubText = $firstSub.text
                if ($parentText -eq $firstSubText) {
                    # Single group approach
                    $parentGroupName = $parentGroupObj.name
                    Write-Host "  --> text fields match => single group: $parentGroupName"

                    try {
                        $encodedGName = [System.Uri]::EscapeDataString($parentGroupName)
                        $gLookup = Invoke-RestMethod `
                            -Uri "$url/api/v2/groups/by-name/$encodedGName" `
                            -Method GET `
                            -Headers @{ Session = $token }
                        $finalGroupId = $gLookup.data.id
                        Write-Host "      Found group ID: $finalGroupId"
                    }
                    catch {
                        Write-Warning "      [ERROR] Could not find group '$parentGroupName': $_"
                    }
                }
                else {
                    # text differs => multiple sub-groups
                    Write-Host "  --> text differs => combine sub_group IDs into new group..."

                    $subGroupIds = @()
                    foreach ($sg in $subs) {
                        $sgName = $sg.name
                        try {
                            $encodedSG = [System.Uri]::EscapeDataString($sgName)
                            $sgLookup = Invoke-RestMethod `
                                -Uri "$url/api/v2/groups/by-name/$encodedSG" `
                                -Method GET `
                                -Headers @{ Session = $token }
                            $foundId = $sgLookup.data.id
                            $subGroupIds += $foundId
                            Write-Host "      + sub_group '$sgName' => ID $foundId"
                        }
                        catch {
                            Write-Warning "      [ERROR] Could not find group '$sgName'. $_"
                        }
                    }

                    if ($subGroupIds) {
                        $uniqueName = "mrgroup_" + ([guid]::NewGuid().ToString())
                        $postBody = @{
                            name       = $uniqueName
                            and_flag   = 0
                            sub_groups = $subGroupIds | ForEach-Object { @{ id = $_ } }
                        } | ConvertTo-Json

                        try {
                            $comboResp = Invoke-RestMethod `
                                -Uri "$url/api/v2/groups" `
                                -Method POST `
                                -Body $postBody `
                                -ContentType "application/json" `
                                -Headers @{ Session = $token }
                            $finalGroupId = $comboResp.data.id
                            Write-Host "      Created combined group '$uniqueName' => ID $finalGroupId"
                        }
                        catch {
                            Write-Warning "      [ERROR] Failed to create combined group: $_"
                        }
                    }
                }
            }
            else {
                # sub-group is empty => single group approach
                Write-Host "  --> sub-group[0] is empty => using parent group name alone"
                $pName = $parentGroupObj.name
                try {
                    $encodedPName = [System.Uri]::EscapeDataString($pName)
                    $oneLookup = Invoke-RestMethod `
                        -Uri "$url/api/v2/groups/by-name/$encodedPName" `
                        -Method GET `
                        -Headers @{ Session = $token }
                    $finalGroupId = $oneLookup.data.id
                    Write-Host "      Found group ID: $finalGroupId"
                }
                catch {
                    Write-Warning "      [ERROR] Could not find group '$pName'. $_"
                }
            }
        }
        else {
            Write-Host "  --> No sub_groups => single group approach..."
            $pName = $parentGroupObj.name
            try {
                $encodedPName = [System.Uri]::EscapeDataString($pName)
                $oneLookup = Invoke-RestMethod `
                    -Uri "$url/api/v2/groups/by-name/$encodedPName" `
                    -Method GET `
                    -Headers @{ Session = $token }
                $finalGroupId = $oneLookup.data.id
                Write-Host "      Found group ID: $finalGroupId"
            }
            catch {
                Write-Warning "      [ERROR] Could not find group '$pName'. $_"
            }
        }
    }
    else {
        Write-Host "  --> No 'group' object => no group override."
    }

    #
    # --- STEP C: We do a GET to see what the server currently has
    # for 'group.id' and 'content_set_roles'
    #
    [int]$serverGroupId = 0
    [array]$serverRoleIds = @()

    try {
        $detailResp = Invoke-RestMethod `
            -Uri "$url/api/v2/user_groups/$userGroupId" `
            -Method GET `
            -Headers @{ Session = $token }

        $serverData = $detailResp.data

        # If the server has 'group.id'
        if ($serverData.group) {
            $serverGroupId = $serverData.group.id
        }

        # If the server has content_set_roles as an array
        if ($serverData.content_set_roles) {
            # Could be an array or single object, adapt:
            if ($serverData.content_set_roles -is [System.Collections.IEnumerable]) {
                # if it's array-like
                $serverRoleIds = $serverData.content_set_roles | Select-Object -ExpandProperty id
            }
            else {
                # if it's a single object
                $serverRoleIds = @($serverData.content_set_roles.id)
            }
        }
        Write-Host "  --> Currently on server: group.id=$serverGroupId, roleIds=($($serverRoleIds -join ','))"
    }
    catch {
        Write-Warning "  [ERROR] Could not GET user group details: $_"
        continue
    }

    #
    # --- STEP D: Decide if we need to patch
    # if the server's group.id != finalGroupId
    # or if $singleRoleId not in $serverRoleIds
    #
    $needsPatch = $false

    if ($serverGroupId -ne $finalGroupId) {
        $needsPatch = $true
    }
    elseif (-not $serverRoleIds -contains $singleRoleId) {
        $needsPatch = $true
    }

    if (-not $needsPatch) {
        Write-Host "  --> No changes needed, skipping patch."
        continue
    }

    #
    # --- STEP E: Build minimal patch body
    # e.g. {
    #   "group": { "id": 1 },
    #   "content_set_roles": [
    #     { "id": 293 }
    #   ]
    # }
    #
    $patchBodyHash = @{
        group = @{ id = $finalGroupId }
        content_set_roles = @(
            @{ id = $singleRoleId }
        )
    }

    $patchBodyJson = $patchBodyHash | ConvertTo-Json
    Write-Host "`n[PATCH] $groupName"

    try {
        $patchResp = Invoke-RestMethod `
            -Uri "$url/api/v2/user_groups/$userGroupId" `
            -Method PATCH `
            -Body $patchBodyJson `
            -ContentType "application/json" `
            -Headers @{ Session = $token }

        Write-Host "    [PATCH SUCCESS] $groupName"
    }
    catch {
        Write-Warning "    [ERROR] Patching user group '$groupName' failed: $_"
    }

    Write-Host "-------------------------------------------------------"
}

Write-Host "`n-- Finished processing user groups --"
