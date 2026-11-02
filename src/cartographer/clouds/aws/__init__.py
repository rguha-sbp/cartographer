from cartographer.clouds.base import Cloud, load_json

AWS = Cloud("aws", "AWS", ("aws",), load_json(__file__, "icons.json"))
