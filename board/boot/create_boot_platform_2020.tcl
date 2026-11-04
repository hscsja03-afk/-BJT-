# Run only with XSCT 2020.2. Generates the independent old-version BSP.
set root [file normalize [file join [file dirname [info script]] .. ..]]
puts "CONTROL_XSCT_VERSION=[version]"
setws $root/build/work/boot_software2020
platform create -name core_2v5_2020 -hw $root/build/work/linux_platform2020/core_2v5.xsa -proc ps7_cortexa9_0 -os standalone
platform generate
puts "CONTROL_2020_BSP_GENERATED"
