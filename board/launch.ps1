$ErrorActionPreference='Stop'
$taskRoot=Split-Path $PSScriptRoot -Parent
$taskExe=Join-Path $taskRoot 'build/dist/desktop/ZynqBjtDesktop/ZynqBjtDesktop.exe'
$taskManifest=Get-Content -LiteralPath (Join-Path $taskRoot 'build/archive_manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$taskArchive=$taskManifest.archives | Where-Object id -EQ 'windows_runtime'
$taskExeRecord=$taskArchive.members | Where-Object path -EQ 'build/dist/desktop/ZynqBjtDesktop/ZynqBjtDesktop.exe'
$taskRestore=!(Test-Path -LiteralPath $taskExe)
if (!$taskRestore) {
  $taskRestore=(Get-FileHash -LiteralPath $taskExe -Algorithm SHA256).Hash.ToLowerInvariant() -ne $taskExeRecord.sha256
}
if ($taskRestore) {
  Add-Type -AssemblyName System.IO.Compression.FileSystem
  $taskZip=Join-Path ([IO.Path]::GetTempPath()) ([guid]::NewGuid().ToString()+'.zip')
  $taskStream=[IO.File]::Create($taskZip)
  try {
    foreach ($taskPart in $taskArchive.parts) {
      $taskFile=Join-Path $taskRoot $taskPart.path
      if ((Get-FileHash -LiteralPath $taskFile -Algorithm SHA256).Hash.ToLowerInvariant() -ne $taskPart.sha256) { throw 'Archive part hash mismatch' }
      $taskInput=[IO.File]::OpenRead($taskFile)
      try { $taskInput.CopyTo($taskStream) } finally { $taskInput.Dispose() }
    }
  } finally { $taskStream.Dispose() }
  try {
    if ((Get-FileHash -LiteralPath $taskZip -Algorithm SHA256).Hash.ToLowerInvariant() -ne $taskArchive.zip_sha256) { throw 'Runtime archive hash mismatch' }
    $taskReader=[IO.Compression.ZipFile]::OpenRead($taskZip)
    try {
      foreach ($taskEntry in $taskReader.Entries) {
        $taskTarget=[IO.Path]::GetFullPath((Join-Path $taskRoot $taskEntry.FullName))
        if (!$taskTarget.StartsWith($taskRoot+'\') -or !$taskEntry.FullName.StartsWith('build/dist/desktop/')) { throw 'Invalid runtime archive path' }
      }
    } finally { $taskReader.Dispose() }
    $taskRuntime=[IO.Path]::GetFullPath((Join-Path $taskRoot 'build/dist/desktop/ZynqBjtDesktop'))
    $taskRuntimeParent=[IO.Path]::GetFullPath((Join-Path $taskRoot 'build/dist/desktop'))
    if ([IO.Path]::GetDirectoryName($taskRuntime) -ne $taskRuntimeParent) { throw 'Invalid runtime directory' }
    if (Test-Path -LiteralPath $taskRuntime) { Remove-Item -LiteralPath $taskRuntime -Recurse -Force }
    Expand-Archive -LiteralPath $taskZip -DestinationPath $taskRoot -Force
  } finally { Remove-Item -LiteralPath $taskZip -Force }
}
Start-Process -FilePath $taskExe -ArgumentList @('--workspace',(Join-Path $taskRoot 'measurements'))
