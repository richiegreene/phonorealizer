/*
 * binser.js — reader for Calvin Rose's binser serialisation format, as used by
 * justidraw (LOVE/Lua) for its .sav files.
 *
 * Format (see lib/binser.lua in the justidraw source):
 *
 *   t < 128    small integer, value = t - 27                       1 byte
 *   t < 192    medium integer, value = next + 0x100*(t-128) - 8192 2 bytes
 *   202        nil
 *   203        IEEE-754 double, big-endian                         9 bytes
 *   204        true
 *   205        false
 *   206        string: length, then raw bytes; registered
 *   207        table: array count, array items, hash count, k/v pairs
 *   208        reference into the visited table (1-based)
 *   209        constructor (custom registered types)
 *   210        function (string.dump payload)
 *   211        named resource
 *
 * Tables are registered in `visited` *before* their contents are read, which is
 * what lets the format express cycles. justidraw leans on this heavily: every
 * vertex holds `r` (next vertex) and `l` (previous vertex), so a track is a
 * doubly-linked chain that nests one level deeper per vertex.
 *
 * That nesting is why this reader is an explicit state machine rather than the
 * obvious recursive descent — a real score reaches ~50,000 vertices, and a
 * recursive parser overflows the JS call stack long before it gets there.
 */

const NIL = 202;
const DOUBLE = 203;
const TRUE = 204;
const FALSE = 205;
const STRING = 206;
const TABLE = 207;
const REFERENCE = 208;
const CONSTRUCTOR = 209;
const FUNCTION = 210;
const RESOURCE = 211;

/**
 * A Lua table. The array part (Lua indices 1..n) and the hash part are kept
 * separate, matching the wire format, so that `t.arr[0]` is Lua's `t[1]` and
 * string keys never collide with numeric ones.
 */
export class LuaTable {
  constructor() {
    this.arr = [];
    this.map = new Map();
  }

  /** Lua `t[key]`, for string/other non-array-index keys. */
  get(key) {
    return this.map.get(key);
  }

  /** Lua `t[i]` for 1-based integer i, checking the array part first. */
  at(i) {
    if (i >= 1 && i <= this.arr.length) return this.arr[i - 1];
    return this.map.get(i);
  }

  get length() {
    return this.arr.length;
  }
}

const utf8 = new TextDecoder('utf-8');

class Reader {
  constructor(bytes) {
    this.bytes = bytes;
    this.view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    this.pos = 0;
    this.visited = [];
  }

  /**
   * binser's `number_from_str`: the same small/medium/double encoding as the
   * tag byte, but always interpreted as a number. Used for table counts,
   * string lengths and reference ids.
   */
  readNumber() {
    const b = this.bytes[this.pos];
    if (b < 128) {
      this.pos += 1;
      return b - 27;
    }
    if (b < 192) {
      const v = this.bytes[this.pos + 1] + 0x100 * (b - 128) - 8192;
      this.pos += 2;
      return v;
    }
    // Anything >= 192 in numeric position is the double marker (203).
    const v = this.view.getFloat64(this.pos + 1, false);
    this.pos += 9;
    return v;
  }

  readString() {
    const len = this.readNumber();
    const s = utf8.decode(this.bytes.subarray(this.pos, this.pos + len));
    this.pos += len;
    this.visited.push(s);
    return s;
  }

  /** Read any value that is not a table (tables need the outer state machine). */
  readScalar() {
    const t = this.bytes[this.pos];
    if (t < 128) {
      this.pos += 1;
      return t - 27;
    }
    if (t < 192) {
      const v = this.bytes[this.pos + 1] + 0x100 * (t - 128) - 8192;
      this.pos += 2;
      return v;
    }
    switch (t) {
      case NIL:
        this.pos += 1;
        return null;
      case DOUBLE:
        return this.readNumber();
      case TRUE:
        this.pos += 1;
        return true;
      case FALSE:
        this.pos += 1;
        return false;
      case STRING:
        this.pos += 1;
        return this.readString();
      case REFERENCE: {
        this.pos += 1;
        const ref = this.readNumber();
        return this.visited[ref - 1];
      }
      case FUNCTION: {
        // A dumped Lua function. Nothing useful on this side of the fence, but
        // it still has to be stepped over so the stream stays aligned.
        this.pos += 1;
        const len = this.readNumber();
        this.pos += len;
        const stub = { __luaFunction: true };
        this.visited.push(stub);
        return stub;
      }
      case RESOURCE: {
        this.pos += 1;
        const name = this.readValue();
        return { __luaResource: name };
      }
      case CONSTRUCTOR: {
        this.pos += 1;
        const name = this.readValue();
        const count = this.readNumber();
        const args = [];
        for (let i = 0; i < count; i++) args.push(this.readValue());
        const built = { __luaConstructor: name, args };
        this.visited.push(built);
        return built;
      }
      default:
        throw new Error(
          `binser: unknown type byte ${t} at offset ${this.pos}`
        );
    }
  }

  /**
   * Read one complete value. Tables are walked with an explicit frame stack so
   * that deeply nested structures (justidraw's vertex chains) cannot overflow
   * the call stack.
   */
  readValue() {
    const stack = [];
    let carry;
    let haveCarry = false;

    for (;;) {
      if (haveCarry) {
        if (stack.length === 0) return carry;
        const f = stack[stack.length - 1];
        if (f.phase === 0) {
          f.tbl.arr[f.i++] = carry;
        } else if (f.phase === 1) {
          f.key = carry;
          f.phase = 2;
          haveCarry = false;
          continue;
        } else {
          f.tbl.map.set(f.key, carry);
          f.j++;
          f.phase = 1;
        }
        haveCarry = false;
        continue;
      }

      // Nothing pending: ask the innermost table what it still needs.
      if (stack.length > 0) {
        const f = stack[stack.length - 1];
        if (f.phase === 0 && f.i >= f.n) {
          f.m = this.readNumber();
          f.phase = 1;
        }
        if (f.phase === 1 && f.j >= f.m) {
          stack.pop();
          carry = f.tbl;
          haveCarry = true;
          continue;
        }
      }

      // Read a fresh value.
      if (this.bytes[this.pos] === TABLE) {
        this.pos += 1;
        const tbl = new LuaTable();
        this.visited.push(tbl);
        stack.push({
          tbl,
          n: this.readNumber(), // array count
          i: 0,
          m: -1, // hash count, read once the array part is done
          j: 0,
          key: undefined,
          phase: 0,
        });
        continue;
      }

      carry = this.readScalar();
      haveCarry = true;
    }
  }
}

/**
 * Deserialise every value in a binser stream.
 * @param {ArrayBuffer|Uint8Array} data
 * @returns {Array} the values, in order
 */
export function deserialize(data) {
  const bytes = data instanceof Uint8Array ? data : new Uint8Array(data);
  const r = new Reader(bytes);
  const out = [];
  while (r.pos < bytes.length) out.push(r.readValue());
  return out;
}

/** Deserialise and return only the first value — how justidraw reads a song. */
export function deserializeOne(data) {
  const bytes = data instanceof Uint8Array ? data : new Uint8Array(data);
  return new Reader(bytes).readValue();
}
