from flask import Flask, request, jsonify
from flask_cors import CORS

import os, sys

# import requests
from invokes import invoke_http

import pika
import json
from dotenv import load_dotenv

from flasgger import Swagger

app = Flask(__name__)
CORS(app)

# Initialize flasgger 
app.config['SWAGGER'] = {
    'title': 'Group Creation Complex Microservice',
    'version': 1.0,
    "openapi": "3.0.2",
    'description': 'API for creating groups with complex attributes'
}
swagger = Swagger(app)


# URLs
group_URL = "https://personal-rc7vnnm9.outsystemscloud.com/GroupAPI_REST/rest/v1/group/"
subgroup_URL = "https://personal-rc7vnnm9.outsystemscloud.com/SubGroupAPI_REST/rest/v1/subgroup/"
user_URL = "https://personal-rc7vnnm9.outsystemscloud.com/UserAPI_REST/rest/v1/user/"

# load and get .env files
load_dotenv()
rabbitmq_host = os.getenv('HOSTNAME')
rabbitmq_port = os.getenv('PORT')
rabbitmq_exchange = os.getenv('EXCHANGE_NAME')
rabbitmq_exchange_type = os.getenv('EXCHANGE_TYPE')

# load and get log queue and routing key
rabbitmq_queue_log = os.getenv('QUEUE_NAME_1')
rabbitmq_routing_key_log = os.getenv('ROUTING_KEY_1') 

# load and get notif queue and routing key
rabbitmq_queue_notif = os.getenv('QUEUE_NAME_2')
rabbitmq_routing_key_notif = os.getenv('ROUTING_KEY_2')  

# Email server details
smtp_server = os.getenv('SMTP_SERVER')
smtp_port = os.getenv('SMTP_PORT')
smtp_username = os.getenv('SMTP_USERNAME')
smtp_password = os.getenv('SMTP_PASSWORD')


# Group Creation complex microservice

@app.route("/groupcreation", methods=['POST'])
def group_creation():
    # Simple check of input format and data of the request are JSON
    """
    Create group with users assigned and subgroups
    ---
    
    requestBody:
        description: Create a new group with subgroups and assign users
        required: true
        content:
            application/json:
                schema:
                    type: array
                    items:
                        oneOf:
                            -   type: object
                                properties:
                                    name:
                                        type: string
                                        description: The name of the group
                                    description:
                                        type: string
                                        description: A brief description of the group
                                    picture:
                                        type: string
                                        description: An image associated
                                    size:
                                        type: integer
                                        description: Number of people in a group
                                    createdById:
                                        type: integer
                                        description: UserId of user who created group
                                    createdByUsername:
                                        type: string
                                        description: Username of user who created group
                                    groupUsers:
                                        type: array
                                        description: Empty array (to be updated when users assigned to group)
                                        items:
                                            type: object
                                required:
                                - name
                                - size
                                - createdById
                                - createdByUsername

                            -   type: array
                                items:
                                    type: object
                                    properties:
                                        name:
                                            type: string
                                            description: The name of the subgroup
                                        description:
                                            type: string
                                            description: A brief description of the subgroup
                                        picture:
                                            type: string
                                            description: An image associated
                                        size:
                                            type: integer
                                            description: Number of people in a subgroup
                                        subGroupUsers:
                                            type: array
                                            description: Empty array (to be updated when users join to subgroup)
                                            items:
                                                type: object
                                required:
                                - name
                                - size
                            -   type: array
                                items:
                                    type: integer
                

    responses:
        201:
            description: Return group with users assigned and subgroups 
        400:
            description: Invalid input
        500: 
            description: Error creating group

    """

    if request.is_json:
        try:
            # Connect to RabbitMQ
            connection = pika.BlockingConnection(pika.ConnectionParameters
                                                (host=rabbitmq_host, port=rabbitmq_port,
                                                heartbeat=3600, blocked_connection_timeout=3600))
            channel = connection.channel()
            
            group_info = request.get_json()[0] #only name is mandatory
            print("\nReceived a group_description in JSON:", group_info)
            subgroup_info = request.get_json()[1] #only name is mandatory
            print("\nReceived a list of subgroups in JSON:", subgroup_info)
            users_id_list = request.get_json()[2] #list of userId
            print("\nReceived a list of usersId in JSON:", users_id_list) 

            # Send group info
            if len(users_id_list) <= int(group_info['size']):
                result = processGroupCreation(group_info,subgroup_info,users_id_list,channel)
            else:
                result = {
                    "code": 400,
                    "message": "Number of users assigned exceeds group size"
                }
            
            # Close the connection
            connection.close()
            return jsonify(result), result["code"]

        except Exception as e:
            # Unexpected error in code
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            ex_str = str(e) + " at " + str(exc_type) + ": " + fname + ": line " + str(exc_tb.tb_lineno)
            print(ex_str)

            return jsonify({
                "code": 500,
                "message": "groupcreation.py internal error: " + ex_str
            }), 500

    # if reached here, not a JSON request.
    return jsonify({
        "code": 400,
        "message": "Invalid JSON input: " + str(request.get_data())
    }), 400

def processGroupCreation(group_info, subgroup_info, users_id_list, channel):

    # Send the group info
    # Invoke the group microservice

    print('\n-----Invoking group microservice-----')
    group_headers = {'X-Group-AppId': request.headers.get('X-Group-AppId'), "X-Group-Key": request.headers.get('X-Group-Key')}
    # create a group in group microservice
    group_result = invoke_http(group_URL, method="POST", json=group_info, headers=group_headers)
    # print(group_result)
    group_result_status = group_result["Result"]
    groupId = group_result["GroupId"]
    # print(groupId)
    print('group_result:', group_result_status) # creation successful

    # get group details 
    unique_group_URL = group_URL + str(groupId)
    # print(unique_group_URL)
    group_dict = invoke_http(unique_group_URL, method="GET", headers=group_headers)
    # print(group_dict)
    group = group_dict["Group"]
    # print(group)

    admin_username = group["createdByUsername"]
    admin_userId = group["createdById"]
    # Define the message
    message = {
        "log type": "Create group",
        "description": f"{admin_username} ({admin_userId}) created a group {group}",
    }

    # Send the message to the exchange
    channel.basic_publish(
        exchange=rabbitmq_exchange,
        routing_key=rabbitmq_routing_key_log,
        body=json.dumps(message),
        properties=pika.BasicProperties(
            delivery_mode=2, # make message persistent
        )
    )

    print(f"Message sent to the exchange '{rabbitmq_exchange}' with routing key '{rabbitmq_routing_key_log}'.")


    # create new subgroup in group 
    # Invoke the subgroup microservice
    subgroup_namelist = []
    subgroup_list = []
    
    subgroup_info = [{**subgrp, 'groupId': groupId} for subgrp in subgroup_info]
    
    for subgrp in subgroup_info: 
        print('\n\n-----Invoking subgroup microservice-----')
        subgroup_headers = {'X-SubGroup-AppId': request.headers.get('X-SubGroup-AppId'), "X-SubGroup-Key": request.headers.get('X-SubGroup-Key')}
        # create subgroup
        # print(subgrp)
        # print(groupId)
        # subgrp['groupId'] = groupId  # Add the groupId directly to the subgroup dictionary
        subgroup_result = invoke_http(subgroup_URL, method="POST", json=subgrp, headers=subgroup_headers)
        # print(subgroup_result)
        subgroup_result_status = subgroup_result["Result"]
        subGroupId = subgroup_result["SubGroupId"]
        print("subgroup_result:", subgroup_result_status, '\n') # creation successful

        # get subgroup details
        unique_subgroup_URL = subgroup_URL + str(subGroupId)
        subgroup_dict = invoke_http(unique_subgroup_URL, method="GET", headers=subgroup_headers)
        subgroup = subgroup_dict["SubGroup"]
        subgroup_list.append(subgroup)
        subgroup_name = subgroup["name"]
        subgroup_namelist.append(subgroup_name)
        

    # Define the message
    message = {
        "log type": "Create group",
        "description": f"{admin_username} ({admin_userId}) created subgroup(s): {subgroup_list} within the group({groupId})",
    }

    # Send the message to the exchange
    channel.basic_publish(
        exchange=rabbitmq_exchange,
        routing_key=rabbitmq_routing_key_log,
        body=json.dumps(message),
        properties=pika.BasicProperties(
            delivery_mode=2, # make message persistent
        )
    )

    print(f"Message sent to the exchange '{rabbitmq_exchange}' with routing key '{rabbitmq_routing_key_log}'.")


    #assign users to group
    assigned_group = processUserAssignment(group,users_id_list,subgroup_namelist, channel)
    if assigned_group:
        updated_group_result_status = invoke_http(unique_group_URL, method="PUT", json=assigned_group, headers=group_headers)
        print("updated_group_result_status: ", updated_group_result_status)

        # Return created group, subgroup, assigned_group
        return {
            "code": 201,
            "data": {
                "subgroup_result": subgroup_list,
                "final_group_result": assigned_group
            }
        }
    else:
        return {
            "code": 400,
            "message": "Number of users assigned exceeds group size"
        }

# User Group Assignment complex microservice
def processUserAssignment(group,user_id_list,subgroup_namelist, channel):
    groupId = group['groupId']
    groupname = group['name']
    users_assigned = [] # list of users assigned
    if len(user_id_list) <= int(group['size']):
        for id in user_id_list:
            # print(id)
            user_headers = {'X-User-AppId': request.headers.get('X-User-AppId'), "X-User-Key": request.headers.get('X-User-Key')}
            unique_user_URL = user_URL + str(id)
            user_dict = invoke_http(unique_user_URL, method="GET", headers=user_headers)
            # print(user_dict)
            user = user_dict["User"]
            username = user["username"]
            assignee = {
                "groupId": groupId,
                "userId": id,
                "username": username
            }
            # print(assignee)
            users_assigned.append(assignee)

            user_email = user["email"]

            subgroup_string = ""
            for i in range(len(subgroup_namelist)-1):
                subgroup_string += subgroup_namelist[i]
                subgroup_string += ", "
            subgroup_string += subgroup_namelist[-1]
            # print(subgroup_string)

            # Define the message
            message = {
                "recipient": user_email,
                "subject": "You have been added into a community",
                "body": f"Dear {username}, you have been added into the {groupname} community. Please proceed to enroll yourself into one of the following projects: {subgroup_string}"
            }

            # Send the message to the exchange
            channel.basic_publish(
                exchange=rabbitmq_exchange,
                routing_key=rabbitmq_routing_key_notif,
                body=json.dumps(message),
                properties=pika.BasicProperties(
                    delivery_mode=2, # make message persistent
                )
            )

            print(f"Message sent to the exchange '{rabbitmq_exchange}' with routing key '{rabbitmq_routing_key_notif}'.")

        group_headers = {'X-Group-AppId': request.headers.get('X-Group-AppId'), "X-Group-Key": request.headers.get('X-Group-Key')}
        assign_users_URL = group_URL + "/assign/" + str(groupId)
        assigned_user_status = invoke_http(assign_users_URL, method="PUT", json=users_assigned, headers=group_headers) 
        print("assigned_user_status: ", assigned_user_status)

        # get new group
        unique_group_URL = group_URL + str(groupId) 
        new_group_dict = invoke_http(unique_group_URL, method="GET", headers=group_headers)
        group = new_group_dict["Group"]
        print("new group: ", group, '\n')

        admin_username = group["createdByUsername"]
        admin_userId = group["createdById"]
        # Define the message
        message = {
            "log type": "Create group",
            "description": f"{admin_username} ({admin_userId}) created a group {group}",
        }

        # Send the message to the exchange
        channel.basic_publish(
            exchange=rabbitmq_exchange,
            routing_key=rabbitmq_routing_key_log,
            body=json.dumps(message),
            properties=pika.BasicProperties(
                delivery_mode=2, # make message persistent
            )
        )

        print(f"Message sent to the exchange '{rabbitmq_exchange}' with routing key '{rabbitmq_routing_key_log}'.")

        return group
    
    else:
        return None
        

# Execute this program if it is run as a main script (not by 'import')
if __name__ == "__main__":
    print("This is flask " + os.path.basename(__file__) +
          " for creating a group...")
    app.run(host="0.0.0.0", port=5000, debug=True)