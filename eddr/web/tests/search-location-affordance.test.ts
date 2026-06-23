import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const resultLanes = readFileSync(join(root, 'src/features/search/ResultLanes.tsx'), 'utf8')
const geocodeFlow = readFileSync(join(root, 'src/features/geocode/GeocodeFlow.tsx'), 'utf8')
const styles = readFileSync(join(root, 'src/styles.css'), 'utf8')

test('search result missing-location thumbnails link to geocode flow', () => {
  assert.match(resultLanes, /missingLocation = photo\.latitude === null \|\| photo\.longitude === null/)
  assert.match(geocodeFlow, /p\.latitude === null \|\| p\.longitude === null/)
  assert.match(resultLanes, /event\.stopPropagation\(\)/)
  assert.match(resultLanes, /className="lane-locate-button"/)
  assert.match(resultLanes, /focus_photo_id: photo\.photo_id/)
  assert.match(geocodeFlow, /group\.focus_photo_id/)
  assert.match(styles, /\.lane-locate-button\s*\{[\s\S]*?position:\s*absolute/)
  assert.match(styles, /\.lane-locate-button span\s*\{[\s\S]*?background:\s*#ef4444/)
})
