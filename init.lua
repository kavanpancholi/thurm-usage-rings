local settings = thurm.settings or {}
local python = settings.python or "/usr/bin/python3"
local slot = settings.slot or "window.bottom_trailing"
local every = math.max(60, tonumber(settings.every) or 300)
local key = settings.key == nil and "cmd+shift+u" or settings.key
local USAGE = thurm.dir .. "/usage.py"

local BUILTIN = {
  claude = { name = "Claude Code", symbol = "asterisk" },
  codex = { name = "Codex", symbol = "circle.hexagongrid" },
}

local function base64_file(path)
  local r = thurm.exec({ "/usr/bin/base64", "-i", (path:gsub("^~", os.getenv("HOME"))) })
  return r.ok and (r.stdout:gsub("%s", "")) or nil
end

-- The tools to show, in order: built-in ones by name, then `custom` ones with their own command.
local function tools()
  local list = {}
  for _, name in ipairs(settings.tools or { "claude", "codex" }) do
    local t = BUILTIN[name]
    if t then
      list[#list + 1] = {
        id = name, name = t.name, symbol = t.symbol, command = { python, USAGE, settings.demo and "demo" or name },
      }
    end
  end
  for i, c in ipairs(settings.custom or {}) do
    if type(c.command) == "table" and c.name then
      list[#list + 1] = {
        id = "custom" .. i, name = c.name, symbol = c.symbol or "sparkles",
        image = c.icon and base64_file(c.icon), command = c.command,
      }
    end
  end
  return list
end

local reports = {}

local function fetch(tool)
  local r = thurm.exec(tool.command, { timeout = 30 })
  local ok, data = pcall(thurm.json.decode, r.stdout or "")
  if not r.ok or not ok or type(data) ~= "table" then
    local why = (r.stderr ~= "" and r.stderr) or "no answer"
    return { problem = why:gsub("%s+$", "") }
  end
  return data
end

local function highest(report)
  local high
  for _, w in ipairs(report.windows or {}) do
    local used = 100 - w.left
    if not high or used > high then high = used end
  end
  return high
end

local function color(used)
  if used < 50 then return "ffffff" elseif used < 80 then return "ff9f0a" end
  return "ff453a"
end

local function resets(at)
  if not at or at == thurm.json.null then return "Reset" end
  local y, mo, d, h, mi, s = at:match("(%d+)-(%d+)-(%d+)T(%d+):(%d+):(%d+)")
  if not y then return "" end
  local utc = os.time({ year = y, month = mo, day = d, hour = h, min = mi, sec = s })
  local now = os.time(os.date("!*t"))
  local secs = math.max(0, utc - now)
  if secs < 3600 then return string.format("Resets in %d minutes", secs // 60) end
  if secs < 86400 then return string.format("Resets in %dh %dm", secs // 3600, secs % 3600 // 60) end
  return string.format("Resets in %d days", secs // 86400)
end

local function text(t, size, weight, c)
  return { type = "text", text = t, size = size, weight = weight, color = c }
end

local function bar(used, c)
  return { type = "stack", align = "leading", children = {
    { type = "spacer", width = 260, height = 5, fill = "#ffffff33", corner = 3 },
    { type = "spacer", width = math.max(1, 260 * used / 100), height = 5, fill = c, corner = 3 },
  } }
end

local function popover(tool, report)
  local rows = { { type = "row", spacing = 24, children = {
    text(tool.name, 15, "bold"),
    { type = "spacer" }, text(os.date("%H:%M"), 11, nil, "secondary") } } }
  if report.problem then
    rows[#rows + 1] = text(tostring(report.problem), 12, nil, "secondary")
  end
  for _, w in ipairs(report.windows or {}) do
    local used = 100 - w.left
    local c = "#" .. color(used)
    rows[#rows + 1] = { type = "column", spacing = 4, children = {
      { type = "row", children = { text(w.label, 13, "medium"), { type = "spacer" },
        text(string.format("%d%% used", used), 13, "bold", c) } },
      bar(used, c),
      text(resets(w.resets_at), 11, nil, "secondary"),
    } }
  end
  rows[#rows + 1] = text("Click to refresh.", 11, nil, "secondary")
  return { type = "column", spacing = 10, width = 260, children = rows }
end

local function item(tool, report)
  local mark = tool.image and { type = "image", image = tool.image, width = 16, height = 16 }
    or { type = "icon", symbol = tool.symbol, size = 14 }
  mark = { type = "stack", width = 38, height = 38, children = { mark } }
  local high = highest(report)
  local children = { mark }
  if high then
    local png = thurm.exec({ python, USAGE, "ring", tostring(high / 100), color(high) }).stdout
    table.insert(children, 1, { type = "image", image = png, width = 38, height = 38 })
  end
  if report.problem then
    children[#children + 1] = { type = "text", text = "!", size = 9, weight = "bold", color = "#000000",
      width = 14, height = 14, fill = "#ffffff", corner = 7 }
  end
  return {
    type = "stack", align = report.problem and "top_trailing" or "center", width = 38, height = 38,
    children = children, action = { name = "usage.refresh" }, popover = popover(tool, report),
  }
end

local mounted = nil

local function draw()
  local children = {}
  for _, tool in ipairs(tools()) do
    children[#children + 1] = item(tool, reports[tool.id] or { problem = "Loading" })
  end
  local ok, shown = pcall(thurm.ui.mount, slot, "usage", {
    type = "row", fill = "#262626e6", border = "#ffffff1f", corner = 29, padding = 10, spacing = 16,
    children = children,
  })
  mounted = ok and shown
  return ok
end

local function refresh()
  for _, tool in ipairs(tools()) do
    reports[tool.id] = fetch(tool)
  end
  draw()
end

thurm.action{
  name = "usage.refresh",
  title = "Refresh Usage Limits",
  category = "Usage",
  run = function() refresh() end,
}

-- A Thurm without views (thurm.ui.mount) shows the limits in a floating card instead.
local card = nil
local COLS, ROWS = 54, 11

thurm.action{
  name = "usage.rings",
  title = "Usage Rings",
  description = "Show what is left of the Claude and Codex limits",
  category = "Usage",
  run = function(ctx)
    if mounted then
      refresh()
      return
    end
    if card and pcall(thurm.close, card) then
      card = nil
      return
    end
    local pane = ctx.pane or thurm.focused()
    local info = pane and thurm.info(pane)
    local place = { cols = COLS, rows = ROWS, col = 0, row = 0 }
    if info and info.size then
      place.col = math.max(0, info.size.cols - COLS - 2)
      place.row = math.max(0, info.size.rows - ROWS - 1)
    end
    local args = { python, thurm.dir .. "/rings.py" }
    if settings.demo then args[#args + 1] = "--demo" end
    card = thurm.open{
      command = args, env = { USAGE_RINGS_SETTINGS = thurm.json.encode(settings) },
      target = pane, float = true, cells = place,
    }
  end,
}

thurm.on("pane_closed", function(ev)
  if ev.id == card then card = nil end
end)

if key then
  thurm.bind(key, "usage.rings")
end

if type(thurm.ui.mount) == "function" and draw() then
  refresh()
  thurm.every(every, refresh)
end
