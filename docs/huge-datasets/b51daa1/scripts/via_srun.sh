#!/usr/bin/env bash
# Called over ssh from the Mac: stdio of the extractor inside running job $1 (SereneDB on port $2).
exec srun --jobid="$1" --overlap -n1 -u $HPCWORK/hpc-b51daa1/src/serve.sh "$2"
