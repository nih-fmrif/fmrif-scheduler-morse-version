
#!/bin/bash

set -e

for doc in schema config cli running-locally user; do
   # Re-enable if possible to install 'context' package
   # pandoc --metadata-file=metadata.yml -f markdown-smart --toc -t context -s -o ${doc}.pdf -s ${doc}.md
   # Use mdpdf package instead
   mdpdf -o ${doc}.pdf ${doc}.md
done

# misc notes for working with generated pdf:

# double check metadata
# exiftool -a -G1 <pdf>

# double check tag structure
# pdfinfo -struct-text <pdf>

# context variable to be added to metadata if needed:
# include list of tables
# 	lot: true
# include list of figures
# 	lof: true
# (include iff there are tables/figures or it will create an empty ToC)

