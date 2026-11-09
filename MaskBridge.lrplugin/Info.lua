return {
	LrSdkVersion = 15.1,
	LrSdkMinimumVersion = 14.0,

	LrPluginName = LOC("$$$/MaskBridge/PluginName=Mask Bridge"),
	LrPluginID = "com.maskbridge.lightroom",
	LrToolkitIdentifier = "com.maskbridge.lightroom",

	-- Early server startup: preload AI engine when the plugin loads
	LrInitPlugin = "MaskBridgeInit.lua",
	-- Clean server shutdown when Lightroom quits
	LrShutdownPlugin = "MaskBridgeShutdown.lua",

	-- Version info for Plugin Manager
	VERSION = { major = 1, minor = 2, revision = 0, display = "1.2.0" },

	-- Status & diagnostic section in the Plug-in Manager
	LrPluginInfoProvider = "MaskBridgeInfoProvider.lua",

	-- Shared library scripts, loaded with 'require'
	LrToolkitScript = {
		"MaskBridgeUtils.lua",
		"MaskBridgeConfig.lua",
		"dkjson.lua",
	},

	LrExportServiceProvider = {
		title = LOC("$$$/MaskBridge/ExportService/Title=Mask Bridge (Export)"),
		file = "MaskBridgeExportProvider.lua",
	},

	-- Menu in Library > Plug-in Extras
	LrLibraryMenuItems = {
		{
			title = LOC("$$$/MaskBridge/Menu/Library=Mask Bridge Dashboard..."),
			file = "MaskBridgeDashboard.lua",
		},
	},

	-- Menu in File > Plug-in Extras
	LrExportMenuItems = {
		{
			title = LOC("$$$/MaskBridge/Menu/File=Mask Bridge Dashboard..."),
			file = "MaskBridgeDashboard.lua",
		},
	},
}
