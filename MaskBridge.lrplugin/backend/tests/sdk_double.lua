
        _PLUGIN = {path=plugin_path}; WIN_ENV=false
        function LOC(s, ...) return s end
        local orig_open = io.open
        io.open = function(p, mode)
            if p:match("%.log$") then return nil end
            return orig_open(p, mode)
        end
        files={}; deleted={}; render_number=0; restore_calls=0; fail_boost=false
        photo={localIdentifier=1, settings={Exposure2012=1}}
        function photo:getFormattedMetadata(k) return "original.jpg" end
        function photo:getDevelopSettings()
            local t={}; for k,v in pairs(self.settings) do t[k]=v end; return t
        end
        function photo:applyDevelopSettings(s, label)
            if label=="MaskBridge Matte Restore" then restore_calls=restore_calls+1 end
            for k,v in pairs(s) do self.settings[k]=v end
        end
        function photo:createDevelopSnapshot() return not fail_snapshot end
        catalog={}
        function catalog:getTargetPhoto() return target_changed and {} or photo end
        function catalog:withWriteAccessDo(label, fn, opts)
            if label=="Matte restore" and abort_restore then return "aborted" end
            fn(); return "executed"
        end
        local paths={child=function(a,b) return a.."/"..b end,
            parent=function(p) return p:match("(.*)/") end,
            removeExtension=function(p) return (p:gsub("%.[^.]+$", "")) end,
            leafName=function(p) return p:match("([^/]+)$") end,
            getStandardFilePath=function() return "/audit-temp" end}
        local fs={exists=function(p) return files[p] and "file" or false end,
            createDirectory=function(p) files[p]=true end,
            createAllDirectories=function(p) files[p]=true end,
            delete=function(p) deleted[#deleted+1]=p; files[p]=nil; return true end,
            move=function(a,b) files[b]=files[a]; files[a]=nil; return true end}
        local tasks={sleep=function() end, pcall=pcall, startAsyncTask=function(fn) fn() end}
        local dc={goToMasking=function() end, selectMask=function(id) selected_id=id end,
            getSelectedMask=function() return selected_id end,
            startTracking=function() if fail_boost then error("injected SDK error") end end,
            stopTracking=function() end, setValue=function() end, getValue=function() return 0 end}
        local function exportSession(opts)
            if on_render then on_render(opts) end
            render_number=render_number+1
            local p=opts.exportSettings.LR_export_destinationPathPrefix.."/render"..render_number..".jpg"
            files[p]=true
            return {doExportOnCurrentTask=function() end, renditions=function()
                local done=false
                return function()
                    if done then return end; done=true
                    return 1,{waitForRender=function() return true,p end}
                end
            end}
        end
        local imports={LrPathUtils=paths,LrFileUtils=fs,LrTasks=tasks,
            LrApplication={activeCatalog=function() return catalog end},
            LrDevelopController=dc,LrApplicationView={
                getCurrentModuleName=function() return current_module or "develop" end,
                switchToModule=function(name) current_module=name end},
            LrExportSession=exportSession,LrDialogs={},LrProgressScope={}}
        function import(n) return imports[n] or {} end
        package.path=plugin_path.."/?.lua;"..package.path
        utils=require 'MaskBridgeUtils'; j=require 'dkjson'
        utils.getServerPort=function() return 9999 end
        utils.httpPost=function(endpoint, data)
            local p=j.decode(data); if p.output then files[p.output]=true end
            if p.output_path then files[p.output_path]=true end
            return '{"status":"success"}'
        end
        matte=dofile(plugin_path.."/MaskBridgeMatte.lua")
