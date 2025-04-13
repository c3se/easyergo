EasyErgo: Ergonomics for Easy Builders
---

EasyErgo is a LSP server for writing easyconfig (.eb) files. Its aim
is to make contributing to easyconfig *even easier*, by providing:

- highlighting and/or autocompletion of
  - easybuild keywords;
  - easybuild parameters;
  - dependency and version (based on current toolchain/robot-path);
- planned features:
  - easybuild style checker;
  - checksums injection;
  - maybe more...

## Installation & usage

You will soon be able to install EasyErgo from PyPI, for now:

```shell
pip install git+https://github.com/c3se/easyergo.git
```

or via `eb -r EasyErgo-1.0.0.eb`

Run a debug server as:

```shell
easyergo --debug
```

### Emacs with eglot (built-in since Emacs 29) example

```elisp
(define-derived-mode eb-mode python-mode "EB")
(add-to-list 'auto-mode-alist '("\\.eb\\'" . eb-mode))
(add-hook 'eb-mode-hook 'eglot-ensure)
(with-eval-after-load 'eglot
  (add-to-list
   'eglot-server-programs
   `(eb-mode . ("localhost" 8000))))
```

### neovim example

No trivial way to to connect to an existing LSP with `.config/nvim/init.lua`:

```shell
vim.api.nvim_create_autocmd({"BufEnter", "BufWinEnter"}, {
  pattern = {"*.eb"},
  callback = function(args)
    client_id = vim.lsp.start({
      name = 'easyergo',
      cmd = vim.lsp.rpc.connect('127.0.0.1', 8000)
  })
  end
})
```
