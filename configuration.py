"""Private installation settings, kept outside the application repository."""
import copy, json, os
from pathlib import Path
from urllib.parse import urlsplit

APP_ROOT = Path(__file__).resolve().parent

DEFAULT_SETTINGS = {
    "site_root": "",
    "data_root": "",
    "site_url": "https://example.com/",
    "site_label": "example.com",
    "author_name": "Example Author",
    "author_signature": "—Example Author",
    "blyg_title": "Example Author's blyg",
    "feed_description": "Writing by Example Author",
    "blogroll_heading": "Blogroll",
    "twitter_creator": "",
    "favicon": "",
    "default_images": [],
    "main_pages": ["index.html", "portfolio.html", "openers.html", "privacypolicy.html"],
    "non_blyg_pages": ["index.html", "portfolio.html", "openers.html", "privacypolicy.html"],
    "local_hostnames": ["example.com", "www.example.com"],
    "navigation": [
        {"url":"/index.html","image":"home.JPG","label":"Home"},
        {"url":"/privacy.html","image":"privacy.JPG","label":"Privacy policy"},
        {"url":"https://social.example/example","image":"social.JPG","label":"Social profile"},
        {"url":"/portfolio.html","image":"portfolio.JPG","label":"Portfolio"},
        {"url":"/openers.html","image":"openers.JPG","label":"Openers"}
    ],
    "publishing": {
        "remote": "website",
        "branch": "master",
        "ssh_key": "",
        "ssh_user": "",
        "hostname": "",
        "remote_path": "/home/public/.git",
        "hostname_suffix": ""
    },
    "runtime": {"source": "", "python": "", "log": ""}
}

def settings_path():
    override=os.environ.get("BLYNGER_SETTINGS")
    return Path(override).expanduser() if override else Path.home()/"Library/Application Support/Blynger/settings.json"

def _merge(base, values):
    result=copy.deepcopy(base)
    for key,value in values.items():
        if isinstance(value,dict) and isinstance(result.get(key),dict): result[key]=_merge(result[key],value)
        else: result[key]=value
    return result

def validate(values):
    cfg=_merge(DEFAULT_SETTINGS,values)
    if not cfg["site_root"]: raise ValueError("Choose the folder containing your website.")
    if not cfg["data_root"]: raise ValueError("Choose a private Blynger data folder.")
    data_root=Path(cfg["data_root"]).expanduser().resolve()
    if data_root == APP_ROOT or APP_ROOT in data_root.parents:
        raise ValueError("Choose a private Blynger data folder outside the application folder.")
    parsed=urlsplit(cfg["site_url"])
    if parsed.scheme not in ("http","https") or not parsed.hostname: raise ValueError("Enter a complete public website address.")
    cfg["site_url"]=cfg["site_url"].rstrip("/")+"/"
    if not cfg["site_label"]: cfg["site_label"]=parsed.hostname
    for key in ("main_pages","non_blyg_pages","local_hostnames","navigation","default_images"):
        if not isinstance(cfg[key],list): raise ValueError(key+" must be a list.")
    return cfg

def load(path=None):
    path=Path(path or settings_path())
    if not path.is_file(): raise ValueError("Blynger settings are missing: "+str(path))
    return validate(json.loads(path.read_text()))

def save(values,path=None):
    path=Path(path or settings_path()); cfg=validate(values)
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(cfg,ensure_ascii=False,indent=2)+"\n")
    os.chmod(tmp,0o600); os.replace(tmp,path)
    return cfg

def public_view(cfg):
    pub=cfg["publishing"]
    return {k:cfg[k] for k in ("site_root","data_root","site_url","site_label","author_name","author_signature","blyg_title","feed_description","blogroll_heading","twitter_creator")}|{
        "remote":pub["remote"],"branch":pub["branch"],"ssh_key":pub["ssh_key"],"ssh_user":pub["ssh_user"],
        "hostname":pub["hostname"],"remote_path":pub["remote_path"]
    }

def update_from_public(cfg, values):
    result=copy.deepcopy(cfg)
    for key in ("site_root","data_root","site_url","site_label","author_name","author_signature","blyg_title","feed_description","blogroll_heading","twitter_creator"):
        if key in values: result[key]=str(values[key]).strip()
    pub=result["publishing"]
    for key in ("remote","branch","ssh_key","ssh_user","hostname","remote_path"):
        if key in values: pub[key]=str(values[key]).strip()
    return validate(result)
