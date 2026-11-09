-- Mask Bridge - Centralized Configuration
-- All configuration constants should be defined here to ensure consistency

local MaskBridgeConfig = {}

-- =============================================================================
-- Debug Mode
-- Set to false for production builds (packaging script should set this)
-- =============================================================================
MaskBridgeConfig.DEBUG_MODE = false

-- =============================================================================
-- Plugin Information
-- =============================================================================
MaskBridgeConfig.VERSION = "1.2.0"
MaskBridgeConfig.PLUGIN_NAME = "Mask Bridge"

-- =============================================================================
-- Server Configuration
-- =============================================================================
MaskBridgeConfig.DEFAULT_SERVER_PORT = 9876

-- =============================================================================
-- AI Model Configuration
-- =============================================================================
MaskBridgeConfig.DEFAULT_THRESHOLD = 0.35
MaskBridgeConfig.DEFAULT_SMOOTHING = 0

-- =============================================================================
-- Export Defaults
-- =============================================================================
MaskBridgeConfig.DEFAULT_MAX_RESOLUTION = 2048
MaskBridgeConfig.DEFAULT_JPEG_QUALITY = 90

-- =============================================================================
-- URLs
-- =============================================================================
-- "Support Mask Bridge" page: ready-to-install builds, pay what you want from 0. A redirect
-- on nicolasdiolez.com: its target can change without a new plugin release.
MaskBridgeConfig.SUPPORT_URL = "https://nicolasdiolez.com/maskbridge"
-- Source code, MIT licence.
MaskBridgeConfig.SOURCE_URL = "https://github.com/nicolasdiolez/mask-bridge"
-- Help by e-mail.
MaskBridgeConfig.CONTACT_URL = "mailto:maskbridge@nicolasdiolez.com"

return MaskBridgeConfig
