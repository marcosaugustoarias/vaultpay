#!/usr/bin/env node
/**
 * SEC-FE-02 guard-rail: fail the build if risky browser APIs show up in src/.
 *  - dangerouslySetInnerHTML / innerHTML / outerHTML / insertAdjacentHTML / document.write -> XSS sinks
 *  - eval / new Function                                                         -> code injection
 *  - localStorage / sessionStorage                                               -> token exfiltration via XSS
 */
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'

const RULES = [
  [/dangerouslySetInnerHTML/, 'dangerouslySetInnerHTML'],
  [/\.(inner|outer)HTML\s*=/, 'innerHTML/outerHTML assignment'],
  [/insertAdjacentHTML/, 'insertAdjacentHTML'],
  [/document\.write/, 'document.write'],
  [/\beval\s*\(/, 'eval()'],
  [/new\s+Function\s*\(/, 'new Function()'],
  [/\b(localStorage|sessionStorage)\b/, 'Web Storage (tokens must stay in memory)'],
]

function* walk(dir) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) yield* walk(p)
    else if (/\.(t|j)sx?$/.test(p) && !p.includes('/test/') && !/\.test\.(t|j)sx?$/.test(p)) yield p
  }
}

let failures = 0
for (const file of walk('src')) {
  readFileSync(file, 'utf8').split('\n').forEach((line, i) => {
    for (const [re, name] of RULES) {
      if (re.test(line)) {
        console.error(`${file}:${i + 1}  forbidden: ${name}`)
        failures++
      }
    }
  })
}
if (failures) process.exit(1)
console.log('check-security: OK (no unsafe DOM sinks, eval or Web Storage in src/)')
