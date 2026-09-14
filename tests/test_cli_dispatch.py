import ast, os


def test_all_dispatch_targets_exist():
    src = open(os.path.join(os.path.dirname(__file__), '..', 'wowdeck', 'cli.py')).read()
    tree = ast.parse(src)
    defined = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    # find dict literals with string keys mapping to Names inside main()
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main')
    targets = [v.id for n in ast.walk(main) if isinstance(n, ast.Dict) for v in n.values if isinstance(v, ast.Name)]
    assert targets, 'dispatch dict not found'
    missing = [t for t in targets if t not in defined]
    assert not missing, missing
