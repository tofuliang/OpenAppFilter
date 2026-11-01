module("luci.controller.oaf_app_record", package.seeall)

local MAX_UINT32 = 4294967295
local MAX_INT32 = 2147483647
local MAX_PAGE_SIZE = 200

local function trim_value(value)
    if value == nil then
        return ""
    end
    return tostring(value):gsub("^%s+", ""):gsub("%s+$", "")
end

local function normalize_mac_param(value)
    local mac = trim_value(value)
    if mac == "" then
        return nil, true
    end
    if not mac:match("^%x%x:%x%x:%x%x:%x%x:%x%x:%x%x$") then
        return nil, false
    end
    return mac:lower(), true
end

local function parse_integer_param(name, default_value, min_value, max_value)
    local raw = luci.http.formvalue(name)
    local value

    if raw == nil then
        return default_value, false
    end
    raw = trim_value(raw)
    if raw == "" then
        return default_value, false
    end
    if not raw:match("^%d+$") then
        return nil, true
    end
    value = tonumber(raw)
    if not value or value % 1 ~= 0 or value < min_value or value > max_value then
        return nil, true
    end
    return value, true
end

local function parse_page_params()
    local page = parse_integer_param("page", 1, 1, MAX_INT32)
    local page_size = parse_integer_param("page_size", 15, 1, MAX_PAGE_SIZE)
    if page == nil or page_size == nil then
        return nil
    end
    return page, page_size
end

local function parse_history_params()
    local mac, mac_ok = normalize_mac_param(luci.http.formvalue("mac"))
    local start_time, start_time_present = parse_integer_param("start_time", 0, 0, MAX_UINT32)
    local end_time, end_time_present = parse_integer_param("end_time", 0, 0, MAX_UINT32)
    local appid = parse_integer_param("appid", 0, 0, MAX_INT32)
    local page = parse_integer_param("page", 1, 1, MAX_INT32)
    local page_size = parse_integer_param("page_size", 15, 1, MAX_PAGE_SIZE)

    if not mac_ok or start_time == nil or end_time == nil or appid == nil or
        page == nil or page_size == nil then
        return nil, "Invalid request parameters"
    end
    if start_time_present and end_time_present and start_time > end_time then
        return nil, "Invalid time range"
    end
    return {
        mac = mac,
        start_time = start_time,
        end_time = end_time,
        start_time_present = start_time_present,
        end_time_present = end_time_present,
        appid = appid,
        page = page,
        page_size = page_size
    }
end

local function parse_exact_traffic_params()
    local mac, mac_ok = normalize_mac_param(luci.http.formvalue("mac"))
    local start_time = parse_integer_param("start_time", nil, 0, MAX_UINT32)
    local end_time = parse_integer_param("end_time", nil, 0, MAX_UINT32)

    if not mac_ok or start_time == nil or end_time == nil then
        return nil, "Invalid request parameters"
    end
    if start_time % 3600 ~= 0 or end_time % 3600 ~= 0 or start_time >= end_time then
        return nil, "Invalid time range"
    end
    return {
        mac = mac,
        start_time = start_time,
        end_time = end_time
    }
end

local function write_bad_request(message)
    luci.http.status(400, "Bad Request")
    luci.http.write_json({ error = message or "Invalid request parameters" })
end
local function write_backend_error()
    luci.http.status(503, "Service Unavailable")
    luci.http.write_json({ error = "Service Unavailable" })
end


function index()
    entry({"admin", "services", "oaf", "app_record"}, template("oaf/app_record"), _("App Record"), 70).leaf = true
    entry({"admin", "services", "oaf", "api", "app_record", "get_active_app_records"}, call("get_active_app_records")).leaf = true
    entry({"admin", "services", "oaf", "api", "app_record", "get_app_history_records"}, call("get_app_history_records")).leaf = true
    entry({"admin", "services", "oaf", "api", "app_record", "get_app_traffic_stats"}, call("get_app_traffic_stats")).leaf = true
    entry({"admin", "services", "oaf", "api", "app_record", "get_exact_app_traffic_stats"}, call("get_exact_app_traffic_stats")).leaf = true
end

function get_active_app_records()
    local util = require "luci.util"
    local page, page_size = parse_page_params()

    luci.http.prepare_content("application/json")
    if not page then
        write_bad_request("Invalid page parameters")
        return
    end


    local req_obj = {
        api = "get_active_app_records",
        data = {
            page = page,
            page_size = page_size
        }
    }

    local resp_obj = util.ubus("fwx", "common", req_obj)
    if resp_obj and resp_obj.code == 2000 and resp_obj.data then
        luci.http.write_json(resp_obj.data)
    else
        write_backend_error()
    end
end

function get_app_history_records()
    local util = require "luci.util"
    local params, error_message = parse_history_params()

    luci.http.prepare_content("application/json")
    if not params then
        write_bad_request(error_message)
        return
    end

    local data = {
        mac = params.mac,
        appid = params.appid,
        page = params.page,
        page_size = params.page_size
    }
    if params.start_time_present then
        data.start_time = params.start_time
    end
    if params.end_time_present then
        data.end_time = params.end_time
    end
    local req_obj = {
        api = "get_app_history_records",
        data = data
    }

    local resp_obj = util.ubus("fwx", "common", req_obj)
    if resp_obj and resp_obj.code == 2000 and resp_obj.data then
        luci.http.write_json(resp_obj.data)
    else
        write_backend_error()
    end
end

function get_app_traffic_stats()
    local util = require "luci.util"
    local params, error_message = parse_history_params()

    luci.http.prepare_content("application/json")
    if not params then
        write_bad_request(error_message)
        return
    end
    local data = {
        mac = params.mac,
        appid = params.appid
    }
    if params.start_time_present then
        data.start_time = params.start_time
    end
    if params.end_time_present then
        data.end_time = params.end_time
    end
    local req_obj = {
        api = "get_app_traffic_stats",
        data = data
    }

    local resp_obj = util.ubus("fwx", "common", req_obj)
    if resp_obj and resp_obj.code == 2000 and resp_obj.data then
        luci.http.write_json(resp_obj.data)
    else
        write_backend_error()
    end
end

function get_exact_app_traffic_stats()
    local util = require "luci.util"
    local params, error_message = parse_exact_traffic_params()

    luci.http.prepare_content("application/json")
    if not params then
        write_bad_request(error_message)
        return
    end

    local req_obj = {
        api = "get_exact_app_traffic_stats",
        data = params
    }
    local resp_obj = util.ubus("fwx", "common", req_obj)
    if resp_obj and resp_obj.code == 2000 and resp_obj.data then
        luci.http.write_json(resp_obj.data)
    else
        write_backend_error()
    end
end
