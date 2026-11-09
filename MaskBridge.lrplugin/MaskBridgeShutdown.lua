-- MaskBridgeShutdown.lua — Clean server shutdown when Lightroom quits
-- Launched by LrShutdownPlugin to stop the AI backend before the plugin unloads.

local LrTasks = import 'LrTasks'
local MaskBridgeUtils = require 'MaskBridgeUtils'

MaskBridgeUtils._shuttingDown = true
LrTasks.startAsyncTask(function()
    if MaskBridgeUtils.isServerRunning() then
        MaskBridgeUtils.stopServer(nil)
    end
end)
