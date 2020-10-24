# edit-filenames

Renames or moves files using a text editor.

Allows paths to a large number of files to be edited using features of a text
editor, such as search-and-replace or multi-cursor editing.

The text editor to use will be determined from the `VISUAL` or `EDITOR`
environment variables.  The editor alternatively can be explicitly specified via
the `-e`/`--editor` command-line option.  The editor can be set to `sed` or to
other similar tools to non-interactively edit filenames.

Note that tabbed editors typically will need to be passed additional
command-line options to spawn independent instances.  This is necessary for
`edit-filenames` to determine when the edited file is closed.  See the examples
below.

## Examples

* To use Visual Studio Code (`code`) to rename all files in the current
  directory:

    ```shell
    $ edit-filenames -e "code --wait" *
    ```

* To use `sed` to replace "apples" with "bananas" for all filenames in the
  current directory:

    ```shell
    $ edit-filenames -e "sed -i s/apples/bananas/" --non-interactive *
    ```

* To add a `.png` extension to all files in the current directory that are
  identified as PNG images:

    ```shell
    $ file --mime-type * | grep image/png | cut -d : -f 1 \
      | xargs edit-filenames -e "sed -i s/$/.png/" --non-interactive
    ```

Copyright © 2020 James D. Lin.
