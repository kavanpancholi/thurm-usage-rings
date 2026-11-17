local settings = thurm.settings or {}
local key = settings.key == nil and "cmd+shift+u" or settings.key
local python = settings.python or "/usr/bin/python3"
local COLS, ROWS = 54, 11

local card = nil

local function open_card(pane)
  local info = pane and thurm.info(pane)
  local place = { cols = COLS, rows = ROWS, col = 0, row = 0 }
  if info and info.size then
    place.col = math.max(0, info.size.cols - COLS - 2)
    place.row = math.max(0, info.size.rows - ROWS - 1)
  end
  local args = { python, thurm.dir .. "/rings.py" }
  if settings.demo then
    args[#args + 1] = "--demo"
  end
  return thurm.open{
    command = args,
    env = { USAGE_RINGS_SETTINGS = thurm.json.encode(settings) },
    target = pane,
    float = true,
    cells = place,
  }
end

thurm.action{
  name = "usage.rings",
  title = "Usage Rings",
  description = "Show what is left of the Claude and Codex limits in a floating card",
  category = "Usage",
  run = function(ctx)
    if card then
      local ok = pcall(thurm.close, card)
      card = nil
      if ok then
        return
      end
    end
    card = open_card(ctx.pane or thurm.focused())
  end,
}

thurm.on("pane_closed", function(ev)
  if ev.id == card then
    card = nil
  end
end)

if key then
  thurm.bind(key, "usage.rings")
end
