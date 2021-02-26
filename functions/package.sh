#!/bin/sh

set -xeuo pipefail

rm -f packages/c1c-controltower-lifecycle.zip

cd source && zip -r ../packages/c1c-controltower-lifecycle.zip *

