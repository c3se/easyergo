EasyErgo: Ergonomics for Easy Builders
---

EasyErgo is a LSP server for writing easyconfig (.eb) files. Its aim
is to make contributing to easyconfig *even easier*, by providing
**NONE** of these:

- highlighting and/or autocompletion of
  - easybuild keywords;
  - easybuild parameters;
  - dependency and version (based on current toolchain/robot-path);
- checker and/or formater for
  - easybuild style rules;
  - missing checksums;
  - (opt-in) sane parameter orders.

## Installatoin & usage

EasyErgo cannot be installed for now, run a simple server instead:

```shell
# install pygls however you want
python src/easyergo.py
```

In this very simple example, we start the language server and connect
to it directly, for a more ordinary setup where the editor starts up
LSP servers for each workspace, see [no more examples].

[no more examples]: docs/more_examples.md

### Emacs with (built-in since Emacs 29) eglot example

```elisp
(define-derived-mode eb-mode python-mode "EB")
(add-to-list 'auto-mode-alist '("\\.eb\\'" . eb-mode))
(add-hook 'eb-mode-hook 'eglot-ensure)
(with-eval-after-load 'eglot
  (add-to-list
   'eglot-server-programs
   `(eb-mode . ("localhost" 8000))))
```

### neovim/vim example

No trivial way to to connect to an existing LSP, use emacs instead:

```shell
# sudo yum remove neovim vim
alias vim=emacs
alias nvim=emacs
```
