const DEFAULT_MODEL_PREFIX = "area_model";
const ZIP_COUNTER_STORAGE_KEY = "sumo-area-builder.defaultExportCounters";

const textEncoder = new TextEncoder();
const crcTable = createCrcTable();

function createCrcTable() {
  const table = new Uint32Array(256);

  for (let index = 0; index < 256; index += 1) {
    let value = index;
    for (let bit = 0; bit < 8; bit += 1) {
      value = value & 1 ? 0xedb88320 ^ (value >>> 1) : value >>> 1;
    }
    table[index] = value >>> 0;
  }

  return table;
}

function crc32(bytes) {
  let crc = 0xffffffff;

  for (let index = 0; index < bytes.length; index += 1) {
    crc = crcTable[(crc ^ bytes[index]) & 0xff] ^ (crc >>> 8);
  }

  return (crc ^ 0xffffffff) >>> 0;
}

function writeUint16(output, value) {
  output.push(value & 0xff, (value >>> 8) & 0xff);
}

function writeUint32(output, value) {
  output.push(
    value & 0xff,
    (value >>> 8) & 0xff,
    (value >>> 16) & 0xff,
    (value >>> 24) & 0xff,
  );
}

function pushBytes(output, bytes) {
  for (let index = 0; index < bytes.length; index += 1) {
    output.push(bytes[index]);
  }
}

function dosDateTime(date = new Date()) {
  const year = Math.max(date.getFullYear(), 1980);

  const dosTime =
    (date.getHours() << 11) |
    (date.getMinutes() << 5) |
    Math.floor(date.getSeconds() / 2);

  const dosDate =
    ((year - 1980) << 9) |
    ((date.getMonth() + 1) << 5) |
    date.getDate();

  return { dosDate, dosTime };
}

export function sanitizeExportName(rawName) {
  const cleaned = String(rawName ?? "")
    .trim()
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-zA-Z0-9._ -]+/g, "_")
    .replace(/\s+/g, "_")
    .replace(/_+/g, "_")
    .replace(/^[._ -]+|[._ -]+$/g, "");

  return cleaned || null;
}

function readCounters() {
  try {
    return JSON.parse(localStorage.getItem(ZIP_COUNTER_STORAGE_KEY) || "{}");
  } catch {
    return {};
  }
}

function writeCounters(counters) {
  localStorage.setItem(ZIP_COUNTER_STORAGE_KEY, JSON.stringify(counters));
}

export function nextDefaultExportName(date = new Date()) {
  const datePart = date.toISOString().slice(0, 10);
  const key = `${DEFAULT_MODEL_PREFIX}_${datePart}`;
  const counters = readCounters();
  const next = Number(counters[key] ?? 0) + 1;
  counters[key] = next;
  writeCounters(counters);

  return `${key}_${String(next).padStart(3, "0")}`;
}

export function resolveExportFolderName(modelName) {
  return sanitizeExportName(modelName) ?? nextDefaultExportName();
}

export function jsonBlob(value, mimeType = "application/json") {
  return new Blob([JSON.stringify(value, null, 2)], { type: mimeType });
}

async function toUint8Array(value) {
  if (value instanceof Uint8Array) {
    return value;
  }

  if (value instanceof Blob) {
    return new Uint8Array(await value.arrayBuffer());
  }

  if (typeof value === "string") {
    return textEncoder.encode(value);
  }

  return textEncoder.encode(String(value ?? ""));
}

export async function createZipBlob(entries) {
  const output = [];
  const centralDirectory = [];
  const now = new Date();
  const { dosDate, dosTime } = dosDateTime(now);

  for (const entry of entries) {
    const fileName = String(entry.path ?? "").replace(/^\/+/, "");
    if (!fileName || fileName.endsWith("/")) {
      continue;
    }

    const nameBytes = textEncoder.encode(fileName);
    const contentBytes = await toUint8Array(entry.content);
    const checksum = crc32(contentBytes);
    const localHeaderOffset = output.length;

    // Local file header.
    writeUint32(output, 0x04034b50);
    writeUint16(output, 20); // version needed
    writeUint16(output, 0x0800); // UTF-8 file names
    writeUint16(output, 0); // store, no compression
    writeUint16(output, dosTime);
    writeUint16(output, dosDate);
    writeUint32(output, checksum);
    writeUint32(output, contentBytes.length);
    writeUint32(output, contentBytes.length);
    writeUint16(output, nameBytes.length);
    writeUint16(output, 0); // extra length
    pushBytes(output, nameBytes);
    pushBytes(output, contentBytes);

    const centralEntry = [];
    writeUint32(centralEntry, 0x02014b50);
    writeUint16(centralEntry, 20); // version made by
    writeUint16(centralEntry, 20); // version needed
    writeUint16(centralEntry, 0x0800); // UTF-8 file names
    writeUint16(centralEntry, 0); // store, no compression
    writeUint16(centralEntry, dosTime);
    writeUint16(centralEntry, dosDate);
    writeUint32(centralEntry, checksum);
    writeUint32(centralEntry, contentBytes.length);
    writeUint32(centralEntry, contentBytes.length);
    writeUint16(centralEntry, nameBytes.length);
    writeUint16(centralEntry, 0); // extra length
    writeUint16(centralEntry, 0); // comment length
    writeUint16(centralEntry, 0); // disk number
    writeUint16(centralEntry, 0); // internal attributes
    writeUint32(centralEntry, 0); // external attributes
    writeUint32(centralEntry, localHeaderOffset);
    pushBytes(centralEntry, nameBytes);
    centralDirectory.push(...centralEntry);
  }

  const centralDirectoryOffset = output.length;
  output.push(...centralDirectory);
  const centralDirectorySize = centralDirectory.length;
  const entryCount = entries.filter((entry) => String(entry.path ?? "").trim()).length;

  // End of central directory.
  writeUint32(output, 0x06054b50);
  writeUint16(output, 0); // disk number
  writeUint16(output, 0); // central directory disk
  writeUint16(output, entryCount);
  writeUint16(output, entryCount);
  writeUint32(output, centralDirectorySize);
  writeUint32(output, centralDirectoryOffset);
  writeUint16(output, 0); // comment length

  return new Blob([new Uint8Array(output)], { type: "application/zip" });
}
