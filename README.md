# edit-filenames

Renames or moves files using a text editor.

Allows paths to a large number of files to be edited using features of a text
editor, such as search-and-replace or multi-cursor editing.

The text editor to use will be determined from the `VISUAL` or `EDITOR`
environment variables.  The editor alternatively can be explicitly specified via
the `-e`/`--editor` command-line option.

Note that tabbed editors typically will need to be passed additional
command-line options to spawn independent instances.  This is necessary for
`edit-filenames` to determine when the edited file is closed.  For example, to
use Visual Studio Code (`code`) to rename all files in the current directory:

```shell
$ edit-filenames -e "code --wait" *
```

Copyright © 2020 James D. Lin.
