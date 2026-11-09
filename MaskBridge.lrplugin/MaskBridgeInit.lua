-- MaskBridgeInit.lua — Early server startup when the plugin loads
-- Launched by LrInitPlugin to preload the AI engine before the user opens the Dashboard.

local LrTasks = import 'LrTasks'
local LrFileUtils = import 'LrFileUtils'
local LrPathUtils = import 'LrPathUtils'
local MaskBridgeUtils = require 'MaskBridgeUtils'

-- Seed pseudo-random generator once for the Lightroom session
math.randomseed(os.time())

MaskBridgeUtils._shuttingDown = false
LrTasks.startAsyncTask(function()
    local model = LrPathUtils.child(MaskBridgeUtils.getModelDir(), "rfdetr_seg_medium.onnx")
    if LrFileUtils.exists(model) then LrTasks.pcall(function() MaskBridgeUtils.startServer(nil) end) end
    -- Remains alive across Stop/Reload; stopped servers are not auto-restarted.
    while not MaskBridgeUtils._shuttingDown do
        LrTasks.sleep(20)
        if not MaskBridgeUtils._shuttingDown then LrTasks.pcall(MaskBridgeUtils.isServerRunning) end
    end
end)
