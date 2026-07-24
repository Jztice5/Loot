param(
    [string]$HostName = "114.132.72.213",
    [int]$Port = 5432,
    [string]$Database = "loot_test",
    [string]$UserName = "loot_app"
)

$ErrorActionPreference = "Stop"

if ($Database -ne "loot_test") {
    throw "This helper only configures the loot_test database."
}

$securePassword = Read-Host "Password for $UserName@$HostName/$Database" -AsSecureString
$credential = [System.Net.NetworkCredential]::new("", $securePassword)
$encodedUser = [System.Uri]::EscapeDataString($UserName)
$encodedPassword = [System.Uri]::EscapeDataString($credential.Password)
$databaseUrl = "postgresql+psycopg://${encodedUser}:${encodedPassword}@${HostName}:${Port}/${Database}"

$configDirectory = Join-Path $HOME ".loot"
$configPath = Join-Path $configDirectory "database.env"
New-Item -ItemType Directory -Force -Path $configDirectory | Out-Null
[System.IO.File]::WriteAllText(
    $configPath,
    "LOOT_TEST_DATABASE_URL=$databaseUrl`n",
    [System.Text.UTF8Encoding]::new($false)
)

Write-Host "Saved loot_test configuration to $configPath"
Write-Host "The password was not written to the repository or command history."
