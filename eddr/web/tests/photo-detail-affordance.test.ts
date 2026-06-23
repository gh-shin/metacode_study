import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const component = readFileSync(join(root, 'src/features/photos/PhotoDetailView.tsx'), 'utf8')
const styles = readFileSync(join(root, 'src/styles.css'), 'utf8')

test('photo detail navigation buttons show arrow affordances', () => {
  assert.match(component, /aria-label="이전 사진"[\s\S]*?<span aria-hidden="true">‹<\/span>/)
  assert.match(component, /aria-label="다음 사진"[\s\S]*?<span aria-hidden="true">›<\/span>/)
  assert.match(styles, /\.photo-nav\s*\{[\s\S]*?display:\s*flex/)
  assert.match(styles, /\.photo-nav span\s*\{[\s\S]*?border-radius:\s*999px/)
})
