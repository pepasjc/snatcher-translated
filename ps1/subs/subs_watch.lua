-- Watch the subtitle payload while playing: is it resident, and which cue is
-- active? The payload header is MAGIC then the current cue index (-1 = none).
-- Redux's CWD is its own, so the log path is absolute: SUBS_WATCH_OUT, else the system temp folder
local out = io.open(os.getenv('SUBS_WATCH_OUT') or ((os.getenv('TEMP') or '/tmp') .. '/subs_watch.txt'), 'w')
local function W(s) out:write(s .. '\n') out:flush() end
W('frame,resident,cue,lba')

local ffi = require('ffi')
local mem = ffi.cast('uint8_t*', PCSX.getMemPtr())
local function rd8(a) return mem[bit.band(a, 0x1fffff)] end
local function rd32(a)
  a = bit.band(a, 0x1fffff)
  return mem[a] + mem[a+1]*0x100 + mem[a+2]*0x10000 + mem[a+3]*0x1000000
end
local function bcd(b) return bit.rshift(b, 4) * 10 + bit.band(b, 15) end

local BLOB = 0x80117188
local f = 0
_G.keep = {}

-- Also trace every Setloc/Setfilter/ReadS the game issues, with the target
-- sector, so the XA driver's per-line seek pattern shows up in real play.
local CMD = {[0x02]='Setloc', [0x0d]='Setfilter', [0x06]='ReadN', [0x1b]='ReadS'}
local function cdtrace(label, faddr)
  return function()
    local r = PCSX.getRegisters()
    local cmd = bit.band(r.GPR.n.a0, 0xFF)
    if not CMD[cmd] then return false end
    local pp = r.GPR.n.a1
    local extra = ''
    if cmd == 0x02 then
      extra = string.format('lba=%d',
        (bcd(rd8(pp)) * 60 + bcd(rd8(pp + 1))) * 75 + bcd(rd8(pp + 2)) - 150)
    elseif cmd == 0x0d then
      extra = string.format('file=%d chan=%d', rd8(pp), rd8(pp + 1))
    end
    W(string.format('C,%d,%s,%s,ra=%08x', f, CMD[cmd], extra, r.GPR.n.ra))
    return false
  end
end
_G.keep[#_G.keep+1] = PCSX.addBreakpoint(0x8005E918, 'Exec', 4, 'CdControl', cdtrace('C'))
_G.keep[#_G.keep+1] = PCSX.addBreakpoint(0x8005E964, 'Exec', 4, 'CdControlB', cdtrace('B'))
-- The text clipping hunt: these two calls decide how wide a line is.
-- render_text(sjis, x, line, colour, width[sp+0x10], dest[sp+0x14]) writes
-- the rendered width in chars to dest byte 0; 0x80033A18(obj, width_px, 16, 1)
-- resizes the text object's textured quad. A line that draws correctly and
-- then clips has to show a second call here - this says which one and with
-- what width.
local rt_slot, rq_slot = #_G.keep + 1, #_G.keep + 2
local function rt_cb()
    local r = PCSX.getRegisters()
    local sp = r.GPR.n.sp
    W(string.format('T,%d,str=%08x,x=%d,line=%d,col=%d,w=%d,dest=%08x,ra=%08x',
      f, r.GPR.n.a0, r.GPR.n.a1, r.GPR.n.a2, r.GPR.n.a3,
      rd32(sp + 0x10), rd32(sp + 0x14), r.GPR.n.ra))
    _G.rearm_rt = true
    return false
end
local function rq_cb()
    local r = PCSX.getRegisters()
    -- the body text object is the one sized to the full 256px canvas, as
    -- opposed to the 72px nameplate
    if r.GPR.n.a1 == 256 then _G.textobj = r.GPR.n.a0 end
    W(string.format('Z,%d,obj=%08x,wpx=%d,h=%d,d=%d,ra=%08x', f,
      r.GPR.n.a0, r.GPR.n.a1, r.GPR.n.a2, r.GPR.n.a3, r.GPR.n.ra))
    _G.rearm_rq = true
    return false
end

-- The body-text call site itself (0x80047670: jal render_text with line=2 and
-- width in $s6). Hooking the CALLEE cannot see it: the nameplate call runs
-- four instructions earlier in the same frame, the breakpoint dies on that
-- hit, and the re-arm only runs at the next vsync. $s6 is the width the
-- clipped lines are suspected of getting wrong.
local body_slot = #_G.keep + 3
local function body_cb()
  local r = PCSX.getRegisters()
  W(string.format('B,%d,str=%08x,s6=%d,sp10=%d,s1=%08x', f,
    r.GPR.n.a0, r.GPR.n.s6, rd32(r.GPR.n.sp + 0x10), r.GPR.n.s1))
  _G.rearm_body = true
  return false
end

-- Re-armed on a timer: a savestate load silently kills Lua breakpoints, and
-- the first run of this instrumentation captured only pre-load frames - the
-- whole ruins run and the B080 arrival went by unhooked.
local function arm()
  _G.keep[rt_slot] = PCSX.addBreakpoint(0x800367D8, 'Exec', 4, 'render_text', rt_cb)
  _G.keep[rq_slot] = PCSX.addBreakpoint(0x80033A18, 'Exec', 4, 'resize_quad', rq_cb)
  _G.keep[body_slot] = PCSX.addBreakpoint(0x80047670, 'Exec', 4, 'body_text', body_cb)
end
arm()

f, lastcue, lastres, lastfn, lasts0, lastrq, lastct = f or 0, -99, nil, -1, -1, -1, -1
_G.keep[#_G.keep+1] = PCSX.Events.createEventListener('GPU::Vsync', function()
  f = f + 1
  -- every frame: engine queue objects are transient, so log each distinct
  -- (type, args) as it appears - the type-3 window-priming args per scene
  -- are what the subtitle payload needs to fix the first-draw position
  local ctx0 = rd32(0x800ABF64)
  if ctx0 == 0x80010000 then
    local node, n = rd32(ctx0 + 0x1954), 0
    while node >= 0x80000000 and node < 0x80200000 and n < 6 do
      local ty = rd32(node + 4)
      local a0, a1, a2 = rd32(node + 8), rd32(node + 0xC), rd32(node + 0x10)
      local key = string.format('%d:%08x:%08x:%08x', ty, a0, a1, a2)
      if key ~= lastobjkey then
        lastobjkey = key
        W(string.format('O,%d,type=%d,args=%08x,%08x,%08x', f, ty, a0, a1, a2))
      end
      node = rd32(node); n = n + 1
    end
  end
  -- The text canvas and its quad. render_text writes the rendered width in
  -- characters to dest byte 0 (dest = ctx+0x1AD0 for the dialogue call), and
  -- the caller sizes the textured quad with 0x80033A18(obj, width_px, 16, 1).
  -- A line draws correctly and is then clipped at 11 characters - exactly
  -- CODES_PER_ROW, i.e. half the width its 11 pair-glyph codes need - so the
  -- question is whether a SECOND render narrows the quad. Log both on every
  -- change: W = width byte, V = the type-0 object's prim vertices.
  if ctx0 == 0x80010000 then
    local w = rd8(ctx0 + 0x1AD0)
    if w ~= lastw then lastw = w
      W(string.format('W,%d,widthbyte=%d', f, w)) end
    local node, n = rd32(ctx0 + 0x1954), 0
    while node >= 0x80000000 and node < 0x80200000 and n < 6 do
      if rd32(node + 4) == 0 then
        local prim = rd32(node + 0x1C)
        if prim >= 0x80000000 and prim < 0x80200000 then
          local v = {}
          for o = 0x58, 0x72, 2 do
            local h = rd8(prim + o) + rd8(prim + o + 1) * 256
            if h > 32767 then h = h - 65536 end
            v[#v+1] = h
          end
          local key = table.concat(v, ',')
          if key ~= lastvert then lastvert = key
            W(string.format('V,%d,prim=%08x,%s', f, prim, key)) end
        end
      end
      node = rd32(node); n = n + 1
    end
  end

  -- object list census: is our subtitle box still alive after a clear?
  -- (the per-key logger dedups, and the chased dismiss carries the same
  -- args as the blank draw, so neither shows there)
  if f % 30 == 0 and ctx0 == 0x80010000 then
    local node, n, types = rd32(ctx0 + 0x1954), 0, {}
    while node >= 0x80000000 and node < 0x80200000 and n < 8 do
      types[#types+1] = string.format('%d(%x/%x/%x)', rd32(node + 4),
        rd32(node + 0x3C), rd32(node + 0x40), rd32(node + 0x44))
      node = rd32(node); n = n + 1
    end
    local key = table.concat(types, ' ')
    if key ~= lastcensus then
      lastcensus = key
      W(string.format('Q,%d,%s', f, key == '' and '(empty)' or key))
    end
  end
  -- a breakpoint that has fired is dead until re-registered, so re-arm on
  -- the very next frame after any hit, not on a slow timer
  if _G.rearm_rt or _G.rearm_rq or _G.rearm_body or f % 300 == 0 then
    _G.rearm_rt, _G.rearm_rq, _G.rearm_body = false, false, false
    arm()
  end
  if f % 15 ~= 0 then return end
  local bp = rd32(0x80117FFC)
  local res = false
  local cue = -1
  if bp >= 0x8010D000 and bp < 0x80117FFC then
    res = rd32(bp) == 0x53554253
    if res then cue = rd32(bp + 4) end
  end
  -- which scene's payload is this? the cue table follows the code; its
  -- count and first start identify the bank without guessing from the
  -- window word (B080 cue0 = 90229, B020 cue0 = 65375)
  if res then
    local cnt = rd32(bp + 0x10)
    local id = string.format('%d/%d', cnt, rd32(bp + 0x14))
    if id ~= lastbank then lastbank = id
      W(string.format('K,%d,cues=%s', f, id)) end
  end
  local ctx = rd32(0x800ABF64)
  local lba = -1
  if ctx == 0x80010000 then
    local q = ctx + 0x58C
    lba = (bcd(rd8(q)) * 60 + bcd(rd8(q+1))) * 75 + bcd(rd8(q+2)) - 150
  end
  local win = -1
  local lay = -1
  if ctx == 0x80010000 then win = rd32(ctx + 0x1ACC) lay = rd32(ctx + 0x1AFC) end
  -- layout id (type-3 handler 0x8004a20c stores args[1] here): the
  -- panel geometry follows it, so a cold subtitle drawn under the
  -- wrong layout gets the wrong frame position
  if lay ~= lastlay then lastlay = lay
    W(string.format('L,%d,layout=%x', f, lay)) end
  if ctx == 0x80010000 then
    local pf, pc = rd8(ctx + 0x594), rd8(ctx + 0x595)
    local pk = pf * 256 + pc
    if pk ~= lastpoll then lastpoll = pk
      W(string.format('P,%d,pollfile=%d,pollchan=%d,lba=%d', f, pf, pc, lba)) end
  end
  -- The clipped line draws correctly and is then replaced, with NO second
  -- render_text and NO quad resize - so the sprite's geometry must be edited
  -- in place. Poll the body object's prim vertices every frame: that is the
  -- only remaining place the width can shrink.
  if _G.textobj and _G.textobj >= 0x80000000 and _G.textobj < 0x80200000 then
    local prim = rd32(_G.textobj + 0x1C)
    if prim >= 0x80000000 and prim < 0x80200000 then
      local v = {}
      for off = 0x58, 0x72, 2 do
        local h = rd8(prim + off) + rd8(prim + off + 1) * 256
        if h > 32767 then h = h - 65536 end
        v[#v+1] = h
      end
      local key = table.concat(v, ' ')
      if key ~= _G.lastquad then
        _G.lastquad = key
        W(string.format('Q2,%d,obj=%08x,prim=%08x,%s', f, _G.textobj, prim, key))
      end
    end
  end
  if ctx == 0x80010000 then
    local wb = rd8(ctx + 0x1AD0)          -- dest byte 0 = rendered width
    if wb ~= lastwb then lastwb = wb
      W(string.format('W,%d,destwidth=%d', f, wb)) end
  end
  local ff = rd32(0x801D0030)   -- captured Setfilter file (SCRATCH+48)
  local fc = rd32(0x801D0034)   -- chan (+52)
  local fk = ff * 256 + fc
  if fk ~= lastfn then
    lastfn = fk
    W(string.format('F,%d,file=%d,chan=%d', f, ff, fc))
  end
  local s0 = rd32(0x801D003C)   -- captured S000 seek LBA (SCRATCH+60)
  if s0 ~= lasts0 then
    lasts0 = s0
    W(string.format('S,%d,lba=%d', f, s0))
  end
  -- the streaming request block: held (non-null) during S000 dialogue
  -- playback, and it carries the stream identity the poll cannot see
  if ctx == 0x80010000 then
    local req = rd32(ctx + 0x57C)
    local rk = 0
    if req >= 0x80000000 and req < 0x80200000 then
      rk = req + rd8(req + 8) * 0x1000000 + rd8(req + 9) * 0x10000
    end
    if rk ~= lastrq then
      lastrq = rk
      if rk == 0 then
        W(string.format('R,%d,null', f))
      else
        W(string.format('R,%d,req=%08x,file=%d,chan=%d,pos=%d,pos2=%d', f,
          req, rd8(req + 8), rd8(req + 9), rd32(req + 0xC), rd32(req + 0x10)))
      end
    end
  end
  local ct = rd32(0x801D0044)   -- CHAINT (SCRATCH+68)
  if ct ~= lastct and (ct < 5 or ct % 50 == 0) then
    lastct = ct
    W(string.format('T,%d,chaint=%d', f, ct))
  end
  -- On every cue change dump the window/panel state block. The first
  -- subtitle of a voice-only stretch opens its panel with the wrong
  -- geometry; diffing this block between that cold draw and a good warm
  -- draw names the field to fix, instead of guessing at layout objects.
  if cue ~= lastcue and ctx == 0x80010000 then
    local parts = {}
    for off = 0x1AC0, 0x1B7C, 4 do
      parts[#parts+1] = string.format('%x=%08x', off, rd32(ctx + off))
    end
    W(string.format('D,%d,cue=%d,%s', f, cue, table.concat(parts, ',')))
  end
  if res ~= lastres or cue ~= lastcue or f % 300 == 0 then
    -- the heartbeat proves the listener is alive; a session that logs only
    -- its first line means the watcher died, not that nothing happened
    lastres, lastcue = res, cue
    W(string.format('%d,%s,%d,%d,%08x', f, tostring(res), cue, lba, win))
  end
end)
PCSX.resumeEmulator()
W('# resumed')
