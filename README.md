# Sensor prediction
Repository for predictions of the sensors set up by Norbit and stored in a AWS TimeStream database table.

## Installation guide
As conda was used during the development phase and known to be working, it is recommended to use conda.
 ### Using conda
 Alternativily install the packages via conda. Installation guide is found [here](https://docs.conda.io/projects/conda/en/latest/user-guide/install/windows.html).
Create a new environment and install the packages.
```
conda env create --name <env-name> python=3.9 --file environment.yml
```
Activate the environment by 
```
conda activate <env-name>
```
### Using PyPI
To run the project, `python 3.9` needs to be installed. Download can be found [here](https://www.python.org/downloads/).
To install the required packages with `pip` run the command 
```
pip install -r requirements.txt
```
 from the root of the project. 

## Direcory tree for the project

```
│   .env                      
│   .env-template               
│   .gitignore      
│   LICENSE
│   README.md
│   requirements.txt            
│   timestreamquery.py          
│   timestream_ml.ipynb
│   timestream_prophet.ipynb
│
└───lambda
    │   .env
    │   .env-template
    │   Dockerfile
    │   requirements.txt
    │
    └───src
            app.py
            timestreamquery.py
```
### Important mentions
- The lambda folder is the code used in production. The secrets in `.env` is not neccesary for the Docker build to succeed, but needed for local testing of the Docker container. Reference to how to do this is found in the section [Local testing with Docker](#Local-testing-with-Docker)  
- The file `timestreamquery.py` is the same in the root of the project and in `lambda/src`
- The secrets needed for the `.env`-file, outlined in `.env-template` can be found in AWS Secrets Mananger in region Stockholm (eu-north-1) under `prod/timestream-prediction` for production secrets and `dev/timestream-prediction` for dev secrets. The only difference is that the dev secrets store the predictions to a development DynamoDB table.



### Files
- `timestreamquery.py` - Tool for easy reading from AWS TimeStream database. Gotten from https://github.com/awslabs/amazon-timestream-tools/blob/mainline/integrations/sagemaker/timestreamquery.py and changed a bit to support access key and secret key. 
- `timestream_ml.ipynb` - A work in progress file, where multiple models have been tested. It is left here so that one can go to this file if one wants to try to improve the model in the future and get a reference of how the `darts`-package is used.
- `timestream_prophet.ipyngb` - Working code for prediction that turned out to be quite accurate. Final model uses [Prophet from Facebook](https://facebook.github.io/prophet/) to do the predictions. Prophet needs to be retrained when new data is used, but currently the prediction for each sensor takes under 1 second in production. The data basis is the data from the sensors, and the weather [Location forecast from yr.no](https://developer.yr.no/featured-products/forecast/). Used as a basis for `lambda/src/app.py` 
- `lambda/src/app.py` - Code running in production and making predictions. Derived from `timestream_prophet.ipynb`.
- `lambda/Dockerfile` - Dockerfile for creating the docker container image. Build from template found in the [AWS Lambda - Deploy container image](https://docs.aws.amazon.com/lambda/latest/dg/python-image.html) documentation. Adapted with installing of the package `libgomp` as this was needed for the Docker container image to build.


## Docker
As the packages for this project were too large to be deployed to a AWS Lambda function through a ZIP archive file, the Lambda function needed to be deployed through a Docker container image. Documentation on how to install Docker can be found [here](https://docs.docker.com/get-docker/).
### Build docker image
From the `./lambda` folder run 
```
docker build -t sensor-prediction .
```
### Deploying docker image
Full documentation can be found [here](https://docs.aws.amazon.com/lambda/latest/dg/images-create.html#images-upload). Important notices is 
- AWS CLI needs to be installed
- `hello-world` is changed to `sensor-prediction` as built in the previous step
- If the login-command to ECR get stuck, it might have something to do with the need for MFA. Try using a different terminal like PowerShell if on Windows.
- If you are trying to authenticate the AWS ECR with a different profile than the default one, the flag `--profile <profile-name>` needs to be added to the command under section **Upload the image to the Amazon ECR repository**: 1. Authenticate the Docker CLI to your Amazon ECR registry. The command should then be
 ```
aws ecr get-login-password --region eu-west-1 --profile <profile-name> | docker login --username AWS --password-stdin <AWS-account-id>.dkr.ecr.eu-west-1.amazonaws.com
```

After deploying the new docker image, you need to go to 
```
AWS Console in eu-west-1 -> Lambda -> Functions -> sensor-prediction -> Image tab
``` 
Click on `Deploy new image`. Then click on `Browse images` and click on the dropdown menu. Choose the image with the *Image tag* `latest`, and click on `Select image` and `Save`. The new container image is now deployed.


### Local testing with Docker
Create a docker container by running the command under from the root of the project. For the file to work, it is important to add the `.env`-variables described in [Important mentions](#important-mentions)
```
docker run --env-file .\.env -p 9000:8080  sensor-prediction:latest
```
To test if the lambda function runs and doesn't give any errors, invoce the function via a POST request to 
```
http://localhost:9000/2015-03-31/functions/function/invocations
```
This can be through `curl` or a program like `Postman`, but the writer has only been able to test the function by using `Postman`.  
