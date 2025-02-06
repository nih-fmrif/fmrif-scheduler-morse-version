#! /bin/bash
# Set default for ENVFILE if not already set
: ${ENVFILE:=.env}

# Source environment variables safely
while IFS= read -r line; do
    # Skip comments and empty lines
    [[ $line =~ ^[[:space:]]*#.*$ || -z $line ]] && continue
    # Export the variable
    export "$line"
done < <(cat "$ENVFILE" | grep -v '#' )


env|grep -i pg

docker compose up --build