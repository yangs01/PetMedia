# Walks through the whole workflow against a running API and worker (mock mode works).
# Usage, from the project root:  powershell -ExecutionPolicy Bypass -File docs\demo.ps1
# Optional: -ImagePath C:\path\to\photo.jpg  uploads a real product photo.
param(
    [string]$BaseUrl = "http://127.0.0.1:8000/api/v1",
    [string]$ImagePath = "",
    [string]$OutFile = "content_package.zip"
)
$ErrorActionPreference = "Stop"

function Post($Path, $Body) {
    Invoke-RestMethod -Method Post -Uri "$BaseUrl$Path" -ContentType "application/json" -Body ($Body | ConvertTo-Json -Depth 8)
}

function Wait-ForStatus($TaskId, $Status) {
    for ($i = 0; $i -lt 240; $i++) {
        $task = Invoke-RestMethod "$BaseUrl/tasks/$TaskId"
        if ($task.status -eq "FAILED") { throw "Task failed: $($task.error | ConvertTo-Json -Depth 5)" }
        if ($task.status -eq $Status -and -not $task.decision_in_progress) {
            Write-Host "  status: $Status"
            return $task
        }
        Start-Sleep -Milliseconds 500
    }
    throw "Timed out waiting for $Status (is the worker running?)."
}

Write-Host "1. Create a brand and a product"
$suffix = Get-Random
$brand = Post "/brands" @{
    brand_name = "Paws & Play $suffix"
    brand_voice = @("Friendly", "Trustworthy", "Playful")
    target_markets = @("US")
}
$product = Post "/products" @{
    name = "Interactive Cat Ball Toy"
    category = "Cat Toys"
    description = "An interactive toy designed to encourage playtime and exploration."
    key_features = @("Lightweight design", "Rolling ball mechanism", "Suitable for supervised indoor play")
}
if ($ImagePath) {
    # Windows PowerShell 5.1 has no multipart support, so this uses the curl.exe bundled with Windows.
    curl.exe -s -f -F "file=@$ImagePath" "$BaseUrl/products/$($product.id)/images" | Out-Null
    Write-Host "  uploaded product photo"
}

Write-Host "2. Create a task (returns immediately; the worker does the work)"
$created = Post "/tasks" @{
    brand_id = $brand.id
    product_ids = @($product.id)
    target_market = "US"
    channels = @("instagram", "facebook")
    image_count = 4
}
$taskId = $created.task_id
Write-Host "  task: $taskId"

Write-Host "3. Choose one of the generated topics"
Wait-ForStatus $taskId "AWAITING_TOPIC_REVIEW" | Out-Null
$topics = Invoke-RestMethod "$BaseUrl/tasks/$taskId/topics"
$topics | ForEach-Object { Write-Host "  - $($_.title)" }
Post "/tasks/$taskId/topic-decision" @{ action = "select"; selected_topic_id = $topics[0].id } | Out-Null

Write-Host "4. Ask for a revision of the draft"
$task = Wait-ForStatus $taskId "AWAITING_COPY_REVIEW"
Post "/tasks/$taskId/copy-decision" @{
    action = "revise"
    current_version_id = $task.current_version.id
    feedback = "Make this more informative and less sales-oriented."
} | Out-Null

Write-Host "5. Approve the revised draft"
do {
    $task = Wait-ForStatus $taskId "AWAITING_COPY_REVIEW"
} while ($task.current_version.version_number -lt 2)
Post "/tasks/$taskId/copy-decision" @{ action = "approve"; current_version_id = $task.current_version.id } | Out-Null

Write-Host "6. Regenerate slide 2 only"
Wait-ForStatus $taskId "AWAITING_IMAGE_REVIEW" | Out-Null
Post "/tasks/$taskId/image-decision" @{
    action = "regenerate"
    slide_numbers = @(2)
    feedback = "Make slide 2 more minimalistic."
} | Out-Null

Write-Host "7. Approve the images"
do {
    $task = Wait-ForStatus $taskId "AWAITING_IMAGE_REVIEW"
    $slide2 = $task.assets | Where-Object { $_.slide_number -eq 2 }
} while ($slide2.asset_version -lt 2)
Post "/tasks/$taskId/image-decision" @{ action = "approve" } | Out-Null

Write-Host "8. Download the package"
Wait-ForStatus $taskId "READY" | Out-Null
Invoke-WebRequest "$BaseUrl/tasks/$taskId/exports/all" -OutFile $OutFile -UseBasicParsing
Write-Host "Done. Saved $OutFile"
