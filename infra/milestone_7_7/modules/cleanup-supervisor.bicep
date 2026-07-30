targetScope = 'subscription'

@allowed([
  'contract-only'
])
param checkpointMode string = 'contract-only'

@allowed([
  false
])
param deploymentEnabled bool = false

@minValue(1)
@maxValue(12000)
param expectedUsdCents int

@minValue(1)
@maxValue(14999)
param maximumPlausibleUsdCents int

@minValue(2500)
@maxValue(10000)
param uncertaintyContingencyBasisPoints int = 2500

@minValue(12)
@maxValue(12)
param defaultPlannedHours int = 12

@minValue(24)
@maxValue(24)
param hardMaximumHours int = 24

@minValue(12)
@maxValue(12)
param vpnMaximumHours int = 12

@minValue(90)
@maxValue(90)
param minimumCleanupReserveMinutes int = 90

@minValue(11)
@maxValue(11)
param requiredTagCount int = 11

@allowed([
  false
])
param leaseBindingResolved bool = false

@allowed([
  false
])
param cleanupTimerBindingResolved bool = false

output moduleName string = 'cleanup-supervisor'
output checkpointMode string = checkpointMode
output deploymentEnabled bool = deploymentEnabled
output expectedWithinBlock bool = expectedUsdCents <= 12000
output maximumBelowCeiling bool = maximumPlausibleUsdCents < 15000
output uncertaintyContingencyBasisPoints int = uncertaintyContingencyBasisPoints
output defaultPlannedHours int = defaultPlannedHours
output hardMaximumHours int = hardMaximumHours
output vpnMaximumHours int = vpnMaximumHours
output minimumCleanupReserveMinutes int = minimumCleanupReserveMinutes
output requiredTagCount int = requiredTagCount
output leaseBindingResolved bool = leaseBindingResolved
output cleanupTimerBindingResolved bool = cleanupTimerBindingResolved
