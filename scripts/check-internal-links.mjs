import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
import { dirname, extname, join, normalize, relative, resolve } from 'node:path';

const root = process.cwd();
const htmlFiles = readdirSync(root).filter((name) => name.endsWith('.html'));
const failures = [];
const skippedSchemes = /^(?:https?:|mailto:|tel:|data:|javascript:|\/\/)/i;

function targetPath(sourceFile, rawPath) {
  const decoded = decodeURIComponent(rawPath || '');
  const withoutQuery = decoded.split('?')[0];
  if (!withoutQuery) return join(root, sourceFile);
  const base = withoutQuery.startsWith('/') ? root : dirname(join(root, sourceFile));
  let candidate = resolve(base, withoutQuery.replace(/^\//, ''));
  if (existsSync(candidate) && statSync(candidate).isDirectory()) candidate = join(candidate, 'index.html');
  return candidate;
}

function hasAnchor(filePath, anchor) {
  if (!anchor) return true;
  const html = readFileSync(filePath, 'utf8');
  const escaped = anchor.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return new RegExp(`(?:id|name)=["']${escaped}["']`, 'i').test(html);
}

for (const sourceFile of htmlFiles) {
  const html = readFileSync(join(root, sourceFile), 'utf8');
  const references = html.matchAll(/\b(?:href|src)\s*=\s*["']([^"']+)["']/gi);

  for (const match of references) {
    const reference = match[1].trim();
    if (!reference || skippedSchemes.test(reference)) continue;

    const [pathPart, anchor = ''] = reference.split('#', 2);
    let filePath;
    try {
      filePath = targetPath(sourceFile, pathPart);
    } catch {
      failures.push(`${sourceFile}: invalid URL encoding in ${reference}`);
      continue;
    }

    const relativeTarget = normalize(relative(root, filePath));
    if (relativeTarget.startsWith('..') || resolve(filePath) === root) {
      failures.push(`${sourceFile}: path escapes the site root: ${reference}`);
      continue;
    }
    if (!existsSync(filePath)) {
      failures.push(`${sourceFile}: missing target ${reference}`);
      continue;
    }
    if (anchor && extname(filePath).toLowerCase() === '.html' && !hasAnchor(filePath, anchor)) {
      failures.push(`${sourceFile}: missing anchor #${anchor} in ${relativeTarget}`);
    }
  }
}

if (failures.length) {
  console.error(`Found ${failures.length} broken internal link${failures.length === 1 ? '' : 's'}:`);
  failures.forEach((failure) => console.error(`- ${failure}`));
  process.exit(1);
}

console.log(`Checked ${htmlFiles.length} HTML files: all internal links and anchors resolve.`);
