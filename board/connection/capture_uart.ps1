param(
  [Parameter(Mandatory=$true)][ValidatePattern('^COM[0-9]+$')][string]$Port,
  [ValidateRange(1,3600)][int]$Seconds=300,
  [ValidatePattern('^[a-z0-9_]+$')][string]$Label='factory_sd'
)
# Receive only: no commands, DTR, RTS, JTAG operations or device reset.
$ErrorActionPreference='Stop'
$taskRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$taskStamp=Get-Date -Format 'yyyyMMdd_HHmmss'
$taskPrefix=Join-Path $taskRoot "build/logs/uart_${Label}_${taskStamp}"
New-Item -ItemType Directory -Force -Path (Split-Path $taskPrefix -Parent) | Out-Null
$taskSerial=[System.IO.Ports.SerialPort]::new($Port,115200,[System.IO.Ports.Parity]::None,8,[System.IO.Ports.StopBits]::One)
$taskSerial.Handshake=[System.IO.Ports.Handshake]::None
$taskSerial.DtrEnable=$false
$taskSerial.RtsEnable=$false
$taskSerial.ReadTimeout=200
$taskRaw=$null; $taskText=$null; $taskBytes=0; $taskFailure=$null
$taskStarted=[DateTime]::UtcNow.ToString('o')
try {
  $taskSerial.Open()
  $taskRaw=[System.IO.File]::Open("${taskPrefix}.bin",[System.IO.FileMode]::CreateNew,[System.IO.FileAccess]::Write,[System.IO.FileShare]::Read)
  $taskText=[System.IO.StreamWriter]::new("${taskPrefix}.log",$false,[System.Text.UTF8Encoding]::new($false))
  $taskText.AutoFlush=$true
  $taskBuffer=[byte[]]::new(4096)
  Write-Output "UART_CAPTURE_OPEN $Port 115200 8N1 DTR=0 RTS=0 log=${taskPrefix}.log"
  $taskDeadline=[DateTime]::UtcNow.AddSeconds($Seconds)
  while ([DateTime]::UtcNow -lt $taskDeadline) {
    try {$taskCount=$taskSerial.Read($taskBuffer,0,$taskBuffer.Length)}
    catch [System.TimeoutException] {continue}
    if ($taskCount -le 0) {continue}
    $taskRaw.Write($taskBuffer,0,$taskCount); $taskRaw.Flush()
    $taskChunk=[System.Text.Encoding]::ASCII.GetString($taskBuffer,0,$taskCount)
    $taskText.Write($taskChunk); [Console]::Write($taskChunk)
    $taskBytes += $taskCount
  }
} catch {
  $taskFailure=$_.Exception.Message
  throw
} finally {
  if ($taskSerial.IsOpen) {$taskSerial.Close()}
  $taskSerial.Dispose()
  if ($null -ne $taskRaw) {$taskRaw.Dispose()}
  if ($null -ne $taskText) {$taskText.Dispose()}
  @{
    port=$Port; baud=115200; format='8N1'; receive_only=$true; dtr=$false; rts=$false
    started_utc=$taskStarted; ended_utc=[DateTime]::UtcNow.ToString('o')
    bytes_received=$taskBytes; error=$taskFailure
    raw_file="${taskPrefix}.bin"; text_file="${taskPrefix}.log"
    note='Received output must be inspected; capture completion does not prove successful boot.'
  } | ConvertTo-Json | Set-Content -LiteralPath "${taskPrefix}.json" -Encoding utf8
  Write-Output "UART_CAPTURE_CLOSED bytes=$taskBytes error=$taskFailure"
}
