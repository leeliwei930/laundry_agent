package main

import (
	"os"

	"github.com/aws/aws-cdk-go/awscdk/v2"
	"github.com/aws/aws-cdk-go/awscdk/v2/awsiam"
	"github.com/aws/aws-cdk-go/awscdk/v2/awslambda"

	// "github.com/aws/aws-cdk-go/awscdk/v2/awssqs"
	"github.com/aws/constructs-go/constructs/v10"
	"github.com/aws/jsii-runtime-go"
)

type DeploymentStackProps struct {
	awscdk.StackProps
}

func NewDeploymentStack(scope constructs.Construct, id string, props *DeploymentStackProps) awscdk.Stack {
	var sprops awscdk.StackProps
	if props != nil {
		sprops = props.StackProps
	}
	stack := awscdk.NewStack(scope, &id, &sprops)

	return stack
}

func main() {
	defer jsii.Close()

	app := awscdk.NewApp(nil)

	stack := NewDeploymentStack(app, "CamFootageActivitiesAnalyserAgentDeploymentStack", &DeploymentStackProps{
		awscdk.StackProps{
			Env: env(),
		},
	})

	dependenciesLayer := awslambda.NewLayerVersion(stack, jsii.String(
		"lambdaDependenciesLayer",
	), &awslambda.LayerVersionProps{
		Code:               awslambda.AssetCode_FromAsset(jsii.String("../build/dependencies.zip"), nil),
		CompatibleRuntimes: &[]awslambda.Runtime{awslambda.Runtime_PYTHON_3_13()},
	})

	lambdaFunc := awslambda.NewFunction(stack, jsii.String("camFootageActivitiesAnalyserAgentFunction"), &awslambda.FunctionProps{
		Code: awslambda.AssetCode_FromAsset(jsii.String("../build/functions.zip"),
			nil,
		),
		MemorySize:   jsii.Number(256),
		Timeout:      awscdk.Duration_Seconds(jsii.Number(30)),
		Handler:      jsii.String("agent.handler"),
		Runtime:      awslambda.Runtime_PYTHON_3_13(),
		Layers:       &[]awslambda.ILayerVersion{dependenciesLayer},
		Architecture: awslambda.Architecture_ARM_64(),
		Environment: &map[string]*string{
			"APPLICATION_INFERENCE_PROFILE_ARN": jsii.String("arn:aws:bedrock:ap-southeast-1:096778346036:application-inference-profile/m2yc3f0mbts3"),
			"APP_DEBUG":                         jsii.String("WARNING"),
			"R2_ACCESS_KEY_ID":                  jsii.String(os.Getenv("R2_ACCESS_KEY_ID")),
			"R2_SECRET_ACCESS_KEY":              jsii.String(os.Getenv("R2_SECRET_ACCESS_KEY")),
			"R2_ENDPOINT_URL":                   jsii.String(os.Getenv("R2_ENDPOINT_URL")),
			"R2_BUCKET_NAME":                    jsii.String(os.Getenv("R2_BUCKET_NAME")),
		},
	})

	lambdaFunc.AddToRolePolicy(awsiam.NewPolicyStatement(&awsiam.PolicyStatementProps{
		Actions: &[]*string{
			jsii.String("bedrock:InvokeModel"),
			jsii.String("bedrock:InvokeModelWithResponseStream"),
		},
		Resources: &[]*string{jsii.String("*")},
	}))

	stack.AddStackTag(jsii.String("project"), jsii.String("homelab"))
	app.Synth(nil)
}

// env determines the AWS environment (account+region) in which our stack is to
// be deployed. For more information see: https://docs.aws.amazon.com/cdk/latest/guide/environments.html
func env() *awscdk.Environment {
	// If unspecified, this stack will be "environment-agnostic".
	// Account/Region-dependent features and context lookups will not work, but a
	// single synthesized template can be deployed anywhere.
	//---------------------------------------------------------------------------
	// return nil

	// Uncomment if you know exactly what account and region you want to deploy
	// the stack to. This is the recommendation for production stacks.
	//---------------------------------------------------------------------------
	// return &awscdk.Environment{
	//  Account: jsii.String("123456789012"),
	//  Region:  jsii.String("us-east-1"),
	// }

	// Uncomment to specialize this stack for the AWS Account and Region that are
	// implied by the current CLI configuration. This is recommended for dev
	// stacks.
	//---------------------------------------------------------------------------
	return &awscdk.Environment{
		Account: jsii.String(os.Getenv("CDK_DEFAULT_ACCOUNT")),
		Region:  jsii.String(os.Getenv("CDK_DEFAULT_REGION")),
	}
}
